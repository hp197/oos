Changed:

- MHO900 test build: the fan follows the SoC's temperature in eight steps (30 % below 38 deg C, full speed from
  50 deg C) through the kernel's thermal zone instead of running at full speed, as the stock system's fan does
  ([MHO900](docs/mho.md)).
