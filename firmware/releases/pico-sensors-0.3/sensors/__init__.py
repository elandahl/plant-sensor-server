import sensors.aht20 as aht20
import sensors.ens160 as ens160
import sensors.sgp40 as sgp40

# Order matters: more specific probes before generic shared addresses.
DRIVERS = [aht20, ens160, sgp40]
