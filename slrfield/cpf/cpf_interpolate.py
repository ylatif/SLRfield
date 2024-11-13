import numpy as np
from astropy import units as u
from astropy.time import Time, TimeDelta
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
from scipy.interpolate import BarycentricInterpolator
from scipy.constants import speed_of_light


def cpf_interp_azalt(ts_utc_cpf, ts_mjd_cpf, ts_sod_cpf, leap_second_cpf, positions_cpf, t_start, t_end, t_increment, mode, station, coord_type):
    """
    Interpolate the CPF ephemeris and make the prediction in topocentric reference frame.

    Usage: 
        ts_isot,ts_mjd,ts_sod,az,alt,r,tof1 = cpf_interpolate(ts_utc_cpf,ts_mjd_cpf,ts_sod_cpf,leap_second_cpf,positions_cpf,t_start,t_end,t_increment,mode,station,coord_type)
        ts_isot,ts_mjd,ts_sod,az_trans,alt_trans,delta_az,delta_alt,r_trans,tof2 = cpf_interpolate(ts_utc_cpf,ts_mjd_cpf,ts_sod_cpf,leap_second_cpf,positions_cpf,t_start,t_end,t_increment,mode,station,coord_type)

    Inputs:
        ts_utc_cpf -> [str array] iso-formatted UTC for CPF ephemeris 
        ts_mjd_cpf -> [int array] MJD for CPF ephemeris 
        ts_sod_cpf -> [float array] Second of Day for CPF ephemeris 
        leap_second_cpf -> [int array] Leap second for CPF ephemeris 
        positions_cpf -> [2d float array] target positions in cartesian coords in meters w.r.t. ITRF for CPF ephemeris 
        t_start -> [str] starting date and time of ephemeris 
        t_end -> [str] ending date and time of ephemeris
        t_increment -> [float or int] time increment in second for ephemeris interpolation, such as 0.5, 1, 2, 5, etc. 
        mode -> [str] whether to consider the light time; if 'geometric', instantaneous position vector from station to target is computed; 
        if 'apparent', position vector containing light time from station to target is computed.
        station -> [numercial array or list with 3 elements] coordinates of station. It can either be geocentric(x, y, z) coordinates or geodetic(lon, lat, height) coordinates.
        Unit for (x, y, z) are meter, and for (lon, lat, height) are degree and meter.
        coord_type -> [str] coordinates type for coordinates of station; it can either be 'geocentric' or 'geodetic'.

    Outputs:
        (1) If the mode is 'geometric', then the transmitting direction of the laser coincides with the receiving direction at a certain moment. 
        In this case, the light time is not considered and the outputs are
        ts_isot -> [str array] isot-formatted UTC for interpolated prediction
        ts_mjd -> [int array] MJD for interpolated prediction
        ts_sod -> [float array] Second of Day for for interpolated prediction
        az -> [float array] Azimuth for interpolated prediction in degrees
        alt -> [float array] Altitude for interpolated prediction in degrees
        r -> [float array] Range for interpolated prediction in meters
        tof1 -> [float array] Time of flight for interpolated prediction in seconds

        (2) If the mode is 'apparent', then the transmitting direction of the laser is inconsistent with the receiving direction at a certain moment. 
        ts_isot -> [str array] isot-formatted UTC for interpolated prediction
        In this case, the light time is considered and the outputs are
        ts_mjd -> [int array] MJD for interpolated prediction
        ts_sod -> [float array] Second of Day for for interpolated prediction
        az_trans  -> [float array] Transmitting azimuth for interpolated prediction in degrees
        alt_trans -> [float array] Transmitting altitude for interpolated prediction in degrees
        delta_az -> [float array] The difference of azimuth between the receiving direction and the transmitting direction in degrees
        delta_alt -> [float array] The difference of altitude between the receiving direction and the transmitting direction in degrees
        r_trans -> [float array] Transmitting range for interpolated prediction in meters
        tof2 -> [float array] Time of flight for interpolated prediction in seconds
    """
    t_start, t_end = Time(t_start), Time(t_end)
    t_start_interp, t_end_interp = Time(ts_utc_cpf[4]), Time(ts_utc_cpf[-5])

    if t_start < t_start_interp or t_end > t_end_interp:
        raise ValueError('({:s}, {:s}) is outside the interpolation range of prediction ({:s}, {:s})'.format(
            t_start.isot, t_end.isot, t_start_interp.isot, t_end_interp.isot))

    ts = t_list(t_start, t_end, t_increment)
    ts_mjd = ts.mjd.astype(int)
    ts_isot = ts.isot
    ts_sod = iso2sod(ts_isot)

    leap_second = np.zeros_like(ts_mjd)

    ts_mjd_median = np.median(ts_mjd_cpf)
    ts_mjd_demedian = ts_mjd - ts_mjd_median
    ts_mjd_cpf_demedian = ts_mjd_cpf - ts_mjd_median

    if leap_second_cpf.any():  # Identify whether the CPF ephemeris includes the leap second
        leap_second_boundary = np.diff(leap_second_cpf).nonzero()[0][0] + 1
        value = leap_second_cpf[leap_second_boundary]
        mjd_cpf_boundary = ts_mjd_cpf[leap_second_boundary]

        condition = (ts_mjd == mjd_cpf_boundary)

        # If the CPF ephemeris includes the leap second, then we need to identify whether the interpolated prediction includes the leap second.
        if condition.any():
            leap_index = np.where(condition)[0][0]
            leap_second[leap_index:] = value

    ts_quasi_mjd = ts_mjd_demedian + (ts_sod+leap_second)/86400
    ts_quasi_mjd_cpf = ts_mjd_cpf_demedian + (ts_sod_cpf+leap_second_cpf)/86400

    positions = interp_ephem(ts_quasi_mjd, ts_quasi_mjd_cpf, positions_cpf)
    az, alt, r = itrs2horizon(station, ts, positions, coord_type)

    if mode == 'geometric':
        tof1 = 2*r/speed_of_light
        return ts_isot, ts_mjd, ts_sod, az, alt, r, tof1

    elif mode == 'apparent':

        tau = r/speed_of_light
        ts_quasi_mjd_trans = ts_mjd_demedian + (ts_sod+leap_second+tau)/86400
        ts_quasi_mjd_recei = ts_mjd_demedian + (ts_sod+leap_second-tau)/86400
        positions_trans = interp_ephem(
            ts_quasi_mjd_trans, ts_quasi_mjd_cpf, positions_cpf)
        positions_recei = interp_ephem(
            ts_quasi_mjd_recei, ts_quasi_mjd_cpf, positions_cpf)
        az_trans, alt_trans, r_trans = itrs2horizon(
            station, ts, positions_trans, coord_type)
        az_recei, alt_recei, r_recei = itrs2horizon(
            station, ts, positions_recei, coord_type)
        tof2 = 2*r_trans/speed_of_light
        delta_az = az_recei - az_trans
        delta_alt = alt_recei - alt_trans

        return ts_isot, ts_mjd, ts_sod, az_trans, alt_trans, delta_az, delta_alt, r_trans, tof2
    else:
        raise Exception("Mode must be 'geometric' or 'apparent'.")


def cpf_interp_xyz_times(ts_utc_cpf, ts_mjd_cpf, ts_sod_cpf, leap_second_cpf, positions_cpf, times):

    t_start = Time(times[0])
    t_end = Time(times[-1])
    # t_start, t_end = Time(t_start), Time(t_end)
    t_start_interp, t_end_interp = Time(ts_utc_cpf[4]), Time(ts_utc_cpf[-5])

    if t_start < t_start_interp or t_end > t_end_interp:
        raise ValueError('({:s}, {:s}) is outside the interpolation range of prediction ({:s}, {:s})'.format(
            t_start.isot, t_end.isot, t_start_interp.isot, t_end_interp.isot))

    ts = Time(times)
    ts_mjd = ts.mjd.astype(int)
    ts_isot = ts.isot
    ts_sod = iso2sod(ts_isot)

    leap_second = np.zeros_like(ts_mjd)

    ts_mjd_median = np.median(ts_mjd_cpf)
    ts_mjd_demedian = ts_mjd - ts_mjd_median
    ts_mjd_cpf_demedian = ts_mjd_cpf - ts_mjd_median

    if leap_second_cpf.any():  # Identify whether the CPF ephemeris includes the leap second
        leap_second_boundary = np.diff(leap_second_cpf).nonzero()[0][0] + 1
        value = leap_second_cpf[leap_second_boundary]
        mjd_cpf_boundary = ts_mjd_cpf[leap_second_boundary]

        condition = (ts_mjd == mjd_cpf_boundary)

        # If the CPF ephemeris includes the leap second, then we need to identify whether the interpolated prediction includes the leap second.
        if condition.any():
            leap_index = np.where(condition)[0][0]
            leap_second[leap_index:] = value

    ts_quasi_mjd = ts_mjd_demedian + (ts_sod+leap_second)/86400
    ts_quasi_mjd_cpf = ts_mjd_cpf_demedian + (ts_sod_cpf+leap_second_cpf)/86400

    positions = interp_ephem(ts_quasi_mjd, ts_quasi_mjd_cpf, positions_cpf)
    # x, y, z = itrs2gcrf(ts, positions)
    x, y, z = positions[:, 0], positions[:, 1], positions[:, 2]

    return ts_isot, ts_mjd, ts_sod, x, y, z


def cpf_interp_xyz(ts_utc_cpf, ts_mjd_cpf, ts_sod_cpf, leap_second_cpf, positions_cpf, t_start, t_end, t_increment):
    """
    Interpolate the CPF ephemeris and make the prediction in GCRF

    Usage: 
        ts_isot,ts_mjd,ts_sod,az,alt,r,tof1 = cpf_interpolate(ts_utc_cpf,ts_mjd_cpf,ts_sod_cpf,leap_second_cpf,positions_cpf,t_start,t_end,t_increment,mode,station,coord_type)
        ts_isot,ts_mjd,ts_sod,az_trans,alt_trans,delta_az,delta_alt,r_trans,tof2 = cpf_interpolate(ts_utc_cpf,ts_mjd_cpf,ts_sod_cpf,leap_second_cpf,positions_cpf,t_start,t_end,t_increment,mode,station,coord_type)

    Inputs:
        ts_utc_cpf -> [str array] iso-formatted UTC for CPF ephemeris 
        ts_mjd_cpf -> [int array] MJD for CPF ephemeris 
        ts_sod_cpf -> [float array] Second of Day for CPF ephemeris 
        leap_second_cpf -> [int array] Leap second for CPF ephemeris 
        positions_cpf -> [2d float array] target positions in cartesian coords in meters w.r.t. ITRF for CPF ephemeris 
        t_start -> [str] starting date and time of ephemeris 
        t_end -> [str] ending date and time of ephemeris
        t_increment -> [float or int] time increment in second for ephemeris interpolation, such as 0.5, 1, 2, 5, etc. 

    Outputs:
        ts_isot -> [str array] isot-formatted UTC for interpolated prediction
        ts_mjd -> [int array] MJD for interpolated prediction
        ts_sod -> [float array] Second of Day for for interpolated prediction
        x -> [float array] Azimuth for interpolated prediction in degrees
        y -> [float array] Altitude for interpolated prediction in degrees
        z -> [float array] Range for interpolated prediction in meters
    """
    t_start, t_end = Time(t_start), Time(t_end)
    t_start_interp, t_end_interp = Time(ts_utc_cpf[4]), Time(ts_utc_cpf[-5])

    if t_start < t_start_interp or t_end > t_end_interp:
        raise ValueError('({:s}, {:s}) is outside the interpolation range of prediction ({:s}, {:s})'.format(
            t_start.isot, t_end.isot, t_start_interp.isot, t_end_interp.isot))

    ts = t_list(t_start, t_end, t_increment)
    ts_mjd = ts.mjd.astype(int)
    ts_isot = ts.isot
    ts_sod = iso2sod(ts_isot)

    leap_second = np.zeros_like(ts_mjd)

    ts_mjd_median = np.median(ts_mjd_cpf)
    ts_mjd_demedian = ts_mjd - ts_mjd_median
    ts_mjd_cpf_demedian = ts_mjd_cpf - ts_mjd_median

    if leap_second_cpf.any():  # Identify whether the CPF ephemeris includes the leap second
        leap_second_boundary = np.diff(leap_second_cpf).nonzero()[0][0] + 1
        value = leap_second_cpf[leap_second_boundary]
        mjd_cpf_boundary = ts_mjd_cpf[leap_second_boundary]

        condition = (ts_mjd == mjd_cpf_boundary)

        # If the CPF ephemeris includes the leap second, then we need to identify whether the interpolated prediction includes the leap second.
        if condition.any():
            leap_index = np.where(condition)[0][0]
            leap_second[leap_index:] = value

    ts_quasi_mjd = ts_mjd_demedian + (ts_sod+leap_second)/86400
    ts_quasi_mjd_cpf = ts_mjd_cpf_demedian + (ts_sod_cpf+leap_second_cpf)/86400

    positions = interp_ephem(ts_quasi_mjd, ts_quasi_mjd_cpf, positions_cpf)
    x, y, z = itrs2gcrf(ts, positions)

    return ts_isot, ts_mjd, ts_sod, x, y, z


def interp_ephem(ts_quasi_mjd, ts_quasi_mjd_cpf, positions_cpf):
    """
    Interpolate the CPF ephemeris using the 10-point(degree 9) Lagrange polynomial interpolation method. 

    Usage: 
        positions = interp_ephem(ts_quasi_mjd,ts_quasi_mjd_cpf,positions_cpf)

    Inputs:
        Here, the quasi MJD is defined as int(MJD) + (SoD + Leap Second)/86400, which is different from the conventional MJD defination.
        For example, MJD and SoD for '2016-12-31 23:59:60' are 57753.99998842606 and 86400, but the corresponding quasi MJD is 57754.0 with leap second of 0.
        As a comparison, MJD and SoD for '2017-01-01 00:00:00' are 57754.0 and 0, but the corresponding quasi MJD is 57754.00001157408 with leap second of 1.
        The day of '2016-12-31' has 86401 seconds, and for conventional MJD calculation, one second is compressed to a 86400/86401 second. 
        Hence, the quasi MJD is defined for convenience of interpolation.

        ts_quasi_mjd -> [float array] quasi MJD for interpolated prediction
        ts_quasi_mjd_cpf -> [float array] quasi MJD for CPF ephemeris
        positions_cpf -> [2d float array] target positions in cartesian coordinates in meters w.r.t. ITRF for CPF ephemeris. 

    Outputs:
        positions -> [2d float array] target positions in cartesian coordinates in meters w.r.t. ITRF for interpolated prediction.
    """
    positions = []

    m = len(ts_quasi_mjd)
    n = len(ts_quasi_mjd_cpf)

    if m > n:
        for i in range(n-1):
            flags = (ts_quasi_mjd >= ts_quasi_mjd_cpf[i]) & (
                ts_quasi_mjd < ts_quasi_mjd_cpf[i+1])
            if flags.any():
                positions.append(BarycentricInterpolator(
                    ts_quasi_mjd_cpf[i-4:i+6], positions_cpf[i-4:i+6])(ts_quasi_mjd[flags]))
        positions = np.concatenate(positions)
    else:
        for j in range(m):
            boundary = np.diff(
                ts_quasi_mjd[j] >= ts_quasi_mjd_cpf).nonzero()[0][0]
            if ts_quasi_mjd[j] in ts_quasi_mjd_cpf:
                positions.append(positions_cpf[boundary])
            else:
                positions.append(BarycentricInterpolator(
                    ts_quasi_mjd_cpf[boundary-4:boundary+6], positions_cpf[boundary-4:boundary+6])(ts_quasi_mjd[j]))
        positions = np.array(positions)

    return positions


def itrs2horizon(station, ts, positions, coord_type):
    """
    Convert cartesian coordinates of targets in ITRF to spherical coordinates in topocentric reference frame for a specific station.

    Usage: 
        az,alt,rho = itrs2horizon(station,ts,ts_quasi_mjd,positions,coord_type)

    Inputs:
        station -> [numercial array or list with 3 elements] coordinates of station. It can either be geocentric(x, y, z) coordinates or geodetic(lon, lat, height) coordinates.
        Unit for (x, y, z) are meter, and for (lon, lat, height) are degree and meter.
        ts -> [str array] isot-formatted UTC for interpolated prediction
        positions -> [2d float array] target positions in cartesian coordinates in meters w.r.t. ITRF for interpolated prediction.
        coord_type -> [str] coordinates type for coordinates of station; it can either be 'geocentric' or 'geodetic'.

    Outputs:
        az -> [float array] Azimuth for interpolated prediction in degrees
        alt -> [float array] Altitude for interpolated prediction in degrees
        rho -> [float array] Range for interpolated prediction in meters
    """
    if coord_type == 'geocentric':
        x, y, z = station
        site = EarthLocation.from_geocentric(x, y, z, unit='m')
    elif coord_type == 'geodetic':
        lat, lon, height = station
        site = EarthLocation.from_geodetic(lon, lat, height)

    coords = SkyCoord(positions, unit='m',
                      representation_type='cartesian', frame='itrs', obstime=Time(ts))
    horizon = coords.transform_to(AltAz(obstime=Time(ts), location=site))

    az, alt, rho = horizon.az.deg, horizon.alt.deg, horizon.distance.m

    return az, alt, rho


def itrs2gcrf(ts, positions):
    """
    Convert cartesian coordinates of targets in ITRF to GCRF.

    Usage: 
        x,y,z = itrs2horizon(station,ts,ts_quasi_mjd,positions,coord_type)

    Inputs:
        ts -> [str array] isot-formatted UTC for interpolated prediction
        positions -> [2d float array] target positions in cartesian coordinates in meters w.r.t. ITRF for interpolated prediction.

    Outputs:
        x -> [float array] Coordinate x for interpolated prediction in [m]
        y -> [float array] Coordinate y for interpolated prediction in [m]
        z -> [float array] Coordinate z for interpolated prediction in [m]
    """
    coords = SkyCoord(positions, unit='m',
                      representation_type='cartesian', frame='itrs', obstime=Time(ts))
    x, y, z = coords.gcrs.cartesian.xyz.value

    return x, y, z


def iso2sod(ts):
    """
    Calculate the Second of Day from the isot-formatted UTC time sets.

    Usage: 
        sods = iso2sod(ts)

    Inputs:
        ts -> [str array] isot-formatted UTC time sets

    Outputs:
        sods -> [float array] second of day
    """
    sods = []
    for t in ts:
        sod = int(t[11:13])*3600 + int(t[14:16])*60 + float(t[17:])
        sods.append(sod)
    return np.array(sods)


def t_list(t_start, t_end, t_step):
    """
    Generate a time series from the start time, end time, and time step.

    Usage: 
        t = t_list(t_start,t_end,t_step)
    Inputs:
        t_start -> [object of class Astropy Time] Start time
        t_end   -> [object of class Astropy Time] End time
        t_step  -> [float] time step, in [seconds]    
    Outputs:
        t       -> [object of class Astropy Time] Time series
    """
    dt = np.around((t_end - t_start).to(u.second).value)
    t = t_start + TimeDelta(np.arange(0, dt+t_step, t_step), format='sec')
    return t


def next_pass_horizon(ts_utc_cpf, ts_mjd_cpf, ts_sod_cpf, leap_second_cpf, positions_cpf, t_start, t_end, t_step, station, coord_type, cutoff):
    """
    Generate passes prediction for space targets viewed from a ground-based station.

    Inputs:
        ts_utc_cpf -> [str array] iso-formatted UTC for CPF ephemeris 
        ts_mjd_cpf -> [int array] MJD for CPF ephemeris 
        ts_sod_cpf -> [float array] Second of Day for CPF ephemeris 
        leap_second_cpf -> [int array] Leap second for CPF ephemeris 
        positions_cpf -> [2d float array] target positions in cartesian coords in meters w.r.t. ITRF for CPF ephemeris 
        t_start -> [str] starting date and time of ephemeris 
        t_end -> [str] ending date and time of ephemeris
        t_step -> [float or int] time increment in second for ephemeris interpolation
        station -> [numercial array or list with 3 elements] coordinates of station. It can either be geocentric(x, y, z) coordinates or geodetic(lon, lat, height) coordinates.
        Unit for (x, y, z) are meter, and for (lon, lat, height) are degree and meter.
        coord_type -> [str] coordinates type for coordinates of station; it can either be 'geocentric' or 'geodetic'.
        cutoff -> [float] altitude cut-off angle

    Outputs:
        passes -> [2d array] Time table of passes in UTC
    """
    mode = 'geometric'
    ts, ts_mjd, ts_sod, az, alt, r, tof1 = cpf_interp_azalt(
        ts_utc_cpf, ts_mjd_cpf, ts_sod_cpf, leap_second_cpf, positions_cpf, t_start, t_end, t_step, mode, station, coord_type)

    sat_above_horizon = alt > cutoff
    # Find the index of jump nodes between sat_above_horizon and sat_under_horizon
    nodes, = np.diff(sat_above_horizon).nonzero()

    # for targets that never set down the horizon.
    passes = []
    if len(nodes) == 0:
        if sat_above_horizon[0]:
            pass_rise, pass_set = Time(t_start), Time(t_end)
            passes.append([pass_rise.isot, pass_set.isot])
        return passes

    if sat_above_horizon[nodes[0]]:
        nodes = np.append(0, nodes)
    if len(nodes) % 2 != 0:
        nodes = np.append(nodes, len(sat_above_horizon)-1)

    t = t_list(Time(t_start), Time(t_end), t_step)
    boundaries = t[nodes].isot.reshape(len(nodes) // 2, 2)
    seconds = TimeDelta(np.arange(t_step+1), format='sec')

    # Compute the time moment of rise and set accurately with an uncertainty less than one second.
    for rises, sets in boundaries:
        t_start_rise = Time(rises)
        t_end_rise = t_start_rise + seconds[-1]
        ts, ts_mjd, ts_sod, az, alt, r, tof1 = cpf_interp_azalt(
            ts_utc_cpf, ts_mjd_cpf, ts_sod_cpf, leap_second_cpf, positions_cpf, t_start_rise, t_end_rise, 1, mode, station, coord_type)
        sat_above_horizon = alt > cutoff
        pass_rise = t_start_rise + seconds[sat_above_horizon][0]

        t_start_set = Time(sets)
        t_end_set = t_start_set + seconds[-1]
        ts, ts_mjd, ts_sod, az, alt, r, tof1 = cpf_interp_azalt(
            ts_utc_cpf, ts_mjd_cpf, ts_sod_cpf, leap_second_cpf, positions_cpf, t_start_set, t_end_set, 1, mode, station, coord_type)
        sat_above_horizon = alt > cutoff

        if sat_above_horizon[-1]:
            pass_set = t_start_set + seconds[sat_above_horizon][0]
        else:
            pass_set = t_start_set + seconds[sat_above_horizon][-1]
        passes.append([pass_rise.isot, pass_set.isot])
    return passes
