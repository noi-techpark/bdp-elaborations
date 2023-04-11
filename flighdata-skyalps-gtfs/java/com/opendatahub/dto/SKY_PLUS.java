package com.opendatahub.dto;
import java.lang.String;
import java.io.Serializable;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
@JsonIgnoreProperties(ignoreUnknown = false)
public class SKY_PLUS implements Serializable {

    /**
     *
     */
    private static final long serialVersionUID = 1L;
    private fare fare;
    private Double minimumPriceOneWay;
    private Double minimumPriceRoundTrip;

    public SKY_PLUS() {

    }

    public fare getFare() {
        return fare;
    }

    public void setFare(fare fare) {
        this.fare = fare;
    }

    public Double getMinimumPriceOneWay() {
        return minimumPriceOneWay;
    }

    public void setMinimumPriceOneWay(Double minimumPriceOneWay) {
        this.minimumPriceOneWay = minimumPriceOneWay;
    }

    public Double getMinimumPriceRoundTrip() {
        return minimumPriceRoundTrip;
    }

    public void setMinimumPriceRoundTrip(Double minimumPriceRoundTrip) {
        this.minimumPriceRoundTrip = minimumPriceRoundTrip;
    }

    public SKY_PLUS(fare fare, Double minimumPriceOneWay, Double minimumPriceRoundTrip) {
        super();
        this.fare = fare;
        this.minimumPriceOneWay = minimumPriceOneWay;
        this.minimumPriceRoundTrip = minimumPriceRoundTrip;
    }

    @Override
    public String toString() {
        return "SKY_PLUS [fare=" + fare + ", minimumPriceOneWay=" + minimumPriceOneWay + ", minimumPriceRoundTrip=" + minimumPriceRoundTrip + "]";
    }

}
