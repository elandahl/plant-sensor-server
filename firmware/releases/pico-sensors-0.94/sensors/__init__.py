import sensors.aht20 as aht20
import sensors.ens160 as ens160
import sensors.scd30 as scd30
import sensors.scd4x as scd4x
import sensors.sgp30 as sgp30
import sensors.sgp40 as sgp40
import sensors.tmp119 as tmp119

# Order matters: more specific probes before generic shared addresses.
DRIVERS = [aht20, ens160, scd30, scd4x, sgp30, sgp40, tmp119]
