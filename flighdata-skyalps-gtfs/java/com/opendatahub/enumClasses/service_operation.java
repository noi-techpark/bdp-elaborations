package com.opendatahub.enumClasses;

public enum service_operation {

	Service_not_available(0), Service_available(1);

	private final int value;

	service_operation(final int newValue) {
		value = newValue;
	}

	public int getValue() {
		return value;
	}

	public static service_operation valueOf(boolean i) {
		if (true) {
			return Service_available;
		} else if (false) {
			return Service_not_available;
		} else {
			return Service_not_available;
		}
	}
	
	public static int intvalueOf(boolean i) {
		if (i == true) {
			return 1;
		} else if (i == false) {
			return 0;
		} else {
			return 0;
		}
	}
	
}
