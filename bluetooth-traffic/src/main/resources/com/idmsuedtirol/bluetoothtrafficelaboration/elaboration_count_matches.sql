-- SPDX-FileCopyrightText: NOI Techpark <digital@noi.bz.it>
--
-- SPDX-License-Identifier: AGPL-3.0-or-later

/*

BluetoothTrafficElaboration: various elaborations of traffic data

Copyright (C) 2017 IDM Südtirol - Alto Adige - Italy

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

*/
-- Davide Montesin <d@vide.bz>

--
--  input_type_id  = 21
--  output_type_id = 20      # Elaboration type
--

with params as
(
   select   ?::int as period,
            ?::int as station_id,
            21::int as input_type_id,
            20::int as output_type_id
)
,
min_max as
(
   select p.period,
          p.station_id,
          p.output_type_id,
          p.input_type_id,
          (select min(timestamp)
            from measurementhistory eh
           where eh.period = 1
             and eh.station_id = p.station_id
             and eh.type_id = p.input_type_id
          ) min_timestamp, 
          (select max(timestamp)
            from measurementhistory eh
           where eh.period = 1
             and eh.station_id = p.station_id
             and eh.type_id = p.input_type_id
          ) max_timestamp,
          (
          select max(timestamp)::date - 1
            from measurementhistory eh
           where eh.period = p.period
             and eh.station_id = p.station_id
             and eh.type_id = p.output_type_id
          ) elaboration_timestamp
     from params p
)
,
calc_min_max as
(
   select *,
          GREATEST(min_timestamp::date, 
                   elaboration_timestamp,
                   '2017-01-01'::date
                   )::timestamp as start_calc
     from min_max
    where min_timestamp is not null
)
,
series as
(
   select *,
          generate_series(start_calc, 
                          max_timestamp, 
                          period * '1 second'::interval) as time_window_start
     from calc_min_max
)
,
range as
(
   select *, 
          time_window_start + period * '1 second'::interval as time_window_end,
          time_window_start + period / 2 * '1 second'::interval as time_window_center
     from series
)
,
result as (
select null::bigint id,
       current_timestamp created_on,
       period,
       time_window_center as timestamp,
       (
          select count(*)
            from measurementhistory eh
           where eh.period = 1
             and eh.station_id = range.station_id
             and eh.type_id = range.input_type_id
             and time_window_start <= eh.timestamp 
             and eh.timestamp < time_window_end
       ) as value,
       -1 as provenience_id,
       station_id,
       output_type_id as type_id
  from range
)
select deltart((select array_agg(result::intimev2.measurementhistory) from result where value is not null),
               start_calc    + period/2 * '1 second'::interval,
               max_timestamp + period/2 * '1 second'::interval,
               station_id,
               output_type_id,
               period),
       start_calc    + period/2 * '1 second'::interval,
       max_timestamp + period/2 * '1 second'::interval
  from calc_min_max
