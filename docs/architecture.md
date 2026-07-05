# Architecture

Air Monitor separates hardware protocols from collection and presentation:

1. Sensor modules build commands and parse validated frames.
2. Transports own serial-port timing, retries, and frame synchronization.
3. Collectors timestamp readings and expose health state.
4. Outputs can later publish MQTT, log JSON, or feed a local database.

The first milestone is intentionally small: prove the PS1-VOC-1000-MOD's
firmware variant with a read-only probe before introducing a daemon or control
logic.

