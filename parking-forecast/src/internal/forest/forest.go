// SPDX-FileCopyrightText: 2026 NOI Techpark <digital@noi.bz.it>
//
// SPDX-License-Identifier: AGPL-3.0-or-later

// Package forest implements a small, dependency-free Random Forest regressor
// (bagged CART regression trees). It replaces the joint 5-way TensorFlow DNN
// ensemble the old pipeline trained once across every station: here, one
// compact forest is fit independently per station.
//
// Why a forest instead of a single tree or a linear model:
//   - trees split on raw feature values, so weather/time interactions
//     ("weather only matters during peak hours") fall out automatically,
//     without hand-crafted interaction terms
//   - evaluating each tree in the forest separately gives a natural
//     prediction interval (the spread across trees), which is exactly what
//     the old 5-model bootstrap ensemble was doing far more expensively —
//     see PredictStats
package forest

import (
	"math"
	"math/rand"
	"sort"
)

type Config struct {
	NumTrees int
	MaxDepth int
	// MinLeafSamples: a node only splits if both children would have at
	// least this many samples.
	MinLeafSamples int
	// RowSubsample: fraction of rows bootstrap-sampled (with replacement)
	// per tree, e.g. 0.8.
	RowSubsample float64
	// FeatureSubsample: fraction of features considered as split
	// candidates at every node, e.g. 0.7. Smaller values decorrelate trees
	// (classic Random Forest "mtry"), which widens/improves the
	// prediction interval from PredictStats.
	FeatureSubsample float64
	Seed             int64
}

func DefaultConfig() Config {
	return Config{
		NumTrees:         60,
		MaxDepth:         8,
		MinLeafSamples:   20,
		RowSubsample:     0.8,
		FeatureSubsample: 0.7,
		Seed:             1,
	}
}

type node struct {
	Leaf      bool
	Value     float64
	Feature   int
	Threshold float64
	Left      *node
	Right     *node
}

type Forest struct {
	Trees       []*node
	NumFeatures int
}

// Fit trains a Random Forest regressor. X is row-major (len(X) samples,
// each len(X[i]) == same feature count), y is the regression target.
func Fit(X [][]float64, y []float64, cfg Config) *Forest {
	n := len(X)
	if n == 0 {
		return &Forest{}
	}
	nFeatures := len(X[0])

	rng := rand.New(rand.NewSource(cfg.Seed))
	f := &Forest{NumFeatures: nFeatures}

	sampleSize := int(cfg.RowSubsample * float64(n))
	if sampleSize < 1 {
		sampleSize = n
	}
	nCandidateFeatures := max(1, int(math.Round(cfg.FeatureSubsample*float64(nFeatures))))

	for t := 0; t < cfg.NumTrees; t++ {
		idx := make([]int, sampleSize)
		for i := range idx {
			idx[i] = rng.Intn(n)
		}
		tb := &treeBuilder{X: X, y: y, cfg: cfg, nCandidateFeatures: nCandidateFeatures, rng: rng}
		root := tb.build(idx, 0)
		f.Trees = append(f.Trees, root)
	}
	return f
}

type treeBuilder struct {
	X                  [][]float64
	y                  []float64
	cfg                Config
	nCandidateFeatures int
	rng                *rand.Rand
}

func mean(y []float64, idx []int) float64 {
	sum := 0.0
	for _, i := range idx {
		sum += y[i]
	}
	return sum / float64(len(idx))
}

func (tb *treeBuilder) build(idx []int, depth int) *node {
	if depth >= tb.cfg.MaxDepth || len(idx) < 2*tb.cfg.MinLeafSamples {
		return &node{Leaf: true, Value: mean(tb.y, idx)}
	}

	feat, threshold, leftIdx, rightIdx, ok := tb.bestSplit(idx)
	if !ok {
		return &node{Leaf: true, Value: mean(tb.y, idx)}
	}

	return &node{
		Feature:   feat,
		Threshold: threshold,
		Left:      tb.build(leftIdx, depth+1),
		Right:     tb.build(rightIdx, depth+1),
	}
}

// bestSplit scans a random subset of features and, for each, every possible
// split point (samples sorted by that feature's value), picking the
// (feature, threshold) that minimizes the summed within-child variance
// (equivalently, maximizes variance reduction vs. the parent node).
func (tb *treeBuilder) bestSplit(idx []int) (feat int, threshold float64, left, right []int, ok bool) {
	nFeatures := tb.nCandidateFeatures
	candidates := tb.rng.Perm(len(tb.X[0]))[:nFeatures]

	bestSSE := math.Inf(1)
	bestFeat := -1
	var bestThreshold float64

	type pair struct {
		v float64
		y float64
	}
	buf := make([]pair, len(idx))

	for _, f := range candidates {
		for k, i := range idx {
			buf[k] = pair{v: tb.X[i][f], y: tb.y[i]}
		}
		sort.Slice(buf, func(a, b int) bool { return buf[a].v < buf[b].v })

		total, totalSq := 0.0, 0.0
		for _, p := range buf {
			total += p.y
			totalSq += p.y * p.y
		}

		leftSum, leftSumSq := 0.0, 0.0
		minLeaf := tb.cfg.MinLeafSamples
		for i := 0; i < len(buf)-1; i++ {
			leftSum += buf[i].y
			leftSumSq += buf[i].y * buf[i].y
			leftCount := i + 1
			rightCount := len(buf) - leftCount
			if leftCount < minLeaf || rightCount < minLeaf {
				continue
			}
			if buf[i].v == buf[i+1].v {
				continue // can't split between equal values
			}

			rightSum := total - leftSum
			rightSumSq := totalSq - leftSumSq

			leftSSE := leftSumSq - leftSum*leftSum/float64(leftCount)
			rightSSE := rightSumSq - rightSum*rightSum/float64(rightCount)
			sse := leftSSE + rightSSE

			if sse < bestSSE {
				bestSSE = sse
				bestFeat = f
				bestThreshold = (buf[i].v + buf[i+1].v) / 2
			}
		}
	}

	if bestFeat == -1 {
		return 0, 0, nil, nil, false
	}

	for _, i := range idx {
		if tb.X[i][bestFeat] <= bestThreshold {
			left = append(left, i)
		} else {
			right = append(right, i)
		}
	}
	if len(left) == 0 || len(right) == 0 {
		return 0, 0, nil, nil, false
	}

	return bestFeat, bestThreshold, left, right, true
}

func predictOne(n *node, x []float64) float64 {
	for !n.Leaf {
		if x[n.Feature] <= n.Threshold {
			n = n.Left
		} else {
			n = n.Right
		}
	}
	return n.Value
}

// PredictAll returns one prediction per tree in the forest.
func (f *Forest) PredictAll(x []float64) []float64 {
	out := make([]float64, len(f.Trees))
	for i, t := range f.Trees {
		out[i] = predictOne(t, x)
	}
	return out
}

// PredictStats returns mean/lo/hi across the forest's trees: mean is the
// forest's regression estimate, lo/hi are the loPct/hiPct percentiles of the
// individual trees' predictions — the forest's built-in stand-in for the old
// pipeline's 5-model bootstrap ensemble spread.
func (f *Forest) PredictStats(x []float64, loPct, hiPct float64) (mean, lo, hi float64) {
	preds := f.PredictAll(x)
	sort.Float64s(preds)

	sum := 0.0
	for _, p := range preds {
		sum += p
	}
	mean = sum / float64(len(preds))
	lo = percentile(preds, loPct)
	hi = percentile(preds, hiPct)
	return
}

// percentile assumes s is already sorted ascending.
func percentile(s []float64, p float64) float64 {
	if len(s) == 0 {
		return math.NaN()
	}
	if len(s) == 1 {
		return s[0]
	}
	pos := p * float64(len(s)-1)
	lo := int(math.Floor(pos))
	hi := int(math.Ceil(pos))
	if lo == hi {
		return s[lo]
	}
	frac := pos - float64(lo)
	return s[lo]*(1-frac) + s[hi]*frac
}
