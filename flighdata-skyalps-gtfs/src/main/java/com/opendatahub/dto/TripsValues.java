package it.noitechpark.dto;
import java.io.Serializable;
import java.lang.String;
import org.springframework.lang.NonNull;

import it.noitechpark.enumClasses.bikes_allowed;
import it.noitechpark.enumClasses.wheelchair_accessible;
public class TripsValues implements Serializable {

    private static final long serialVersionUID = 1L;
	private String route_id; // read specifications
	@NonNull
	private String service_id;
	@NonNull
	private String trip_id; // scode
	private String trip_headsign;
	private String trip_short_name;
	private String direction_id;// Check if the in the ODH API if a flight departs from Bolzano (in this case
								// value is 0) or arrives to Bolzano (int his case value is 1)
	private String block_id;
	@NonNull
	private String shape_id;
	private wheelchair_accessible wheelchair_accessible;
	private bikes_allowed bikes_allowed;

	public String getRoute_id() {
		return route_id;
	}

	public void setRoute_id(String route_id) {
		this.route_id = route_id;
	}

	public String getService_id() {
		return service_id;
	}

	public void setService_id(String service_id) {
		this.service_id = service_id;
	}

	public String getTrip_id() {
		return trip_id;
	}

	public void setTrip_id(String trip_id) {
		this.trip_id = trip_id;
	}

	public String getTrip_headsign() {
		return trip_headsign;
	}

	public void setTrip_headsign(String trip_headsign) {
		this.trip_headsign = trip_headsign;
	}

	public String getTrip_short_name() {
		return trip_short_name;
	}

	public void setTrip_short_name(String trip_short_name) {
		this.trip_short_name = trip_short_name;
	}

	public String getDirection_id() {
		return direction_id;
	}

	public void setDirection_id(String direction_id) {
		this.direction_id = direction_id;
	}

	public String getBlock_id() {
		return block_id;
	}

	public void setBlock_id(String block_id) {
		this.block_id = block_id;
	}

	public String getShape_id() {
		return shape_id;
	}

	public void setShape_id(String shape_id) {
		this.shape_id = shape_id;
	}

	public wheelchair_accessible getWheelchair_accessible() {
		return wheelchair_accessible;
	}

	public void setWheelchair_accessible(wheelchair_accessible wheelchair_accessible) {
		this.wheelchair_accessible = wheelchair_accessible;
	}

	public bikes_allowed getBikes_allowed() {
		return bikes_allowed;
	}

	public void setBikes_allowed(bikes_allowed bikes_allowed) {
		this.bikes_allowed = bikes_allowed;
	}

	public TripsValues(String route_id, String service_id, String trip_id, String trip_headsign,
			String trip_short_name, String direction_id, String block_id, String shape_id,
			it.noitechpark.enumClasses.wheelchair_accessible wheelchair_accessible,
			it.noitechpark.enumClasses.bikes_allowed bikes_allowed) {
		super();
		this.route_id = route_id;
		this.service_id = service_id;
		this.trip_id = trip_id;
		this.trip_headsign = trip_headsign;
		this.trip_short_name = trip_short_name;
		this.direction_id = direction_id;
		this.block_id = block_id;
		this.shape_id = shape_id;
		this.wheelchair_accessible = wheelchair_accessible;
		this.bikes_allowed = bikes_allowed;
	}

	public TripsValues(String route_id, String service_id, String trip_id, String shape_id) {
		super();
		this.route_id = route_id;
		this.service_id = service_id;
		this.trip_id = trip_id;
		this.shape_id = shape_id;
	}

	public TripsValues() {
		// TODO Auto-generated constructor stub
	}

	@Override
	public String toString() {
		return "TripsValues [route_id=" + route_id + ", service_id=" + service_id + ", trip_id=" + trip_id
				+ ", trip_headsign=" + trip_headsign + ", trip_short_name=" + trip_short_name + ", direction_id="
				+ direction_id + ", block_id=" + block_id + ", shape_id=" + shape_id + ", wheelchair_accessible="
				+ wheelchair_accessible + ", bikes_allowed=" + bikes_allowed + "]";
	}

}