# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-09-27

### Fixed

- A bad AMI login now correctly shows a reauth form to re-enter credentials, instead of crashing with `data_entry_flow.UnknownStep`. Home Assistant automatically starts a reauth flow on `ConfigEntryAuthFailed`, which the config flow did not yet implement; only surfaced once authentication actually failed, so the initial release's tests never hit it.

## [0.1.0] - 2026-09-27

First release. A full rewrite of a local-only, unpublished predecessor, built to replace a proven external script (a systemd-managed Python service parsing raw AMI events and publishing to MQTT) with a native Home Assistant integration.

### Added

- Config flow with a real AMI connection test (host, port, username, password), plus an options flow for which extensions are internal handsets and the minimum digit count for a fallback-detected outgoing number.
- Three push-driven sensors: incoming call, outgoing call, and last call (whichever direction changed most recently, with a `direction` attribute).
- Call classification ported from the proven production script: `Newchannel`/`Newexten`/`Dial` for detecting a new call and its number, `BridgeEnter`/`DialAnswer` for answered calls, and `Hangup` cause-code handling that tells a rejected call, a busy signal, an unanswered call and a normal hangup apart.
- Automatic reconnect on a dropped AMI connection, and pruning of a call that got stuck due to a missed event.
- Test suite (pytest + pytest-homeassistant-custom-component) covering the call-classification logic in isolation, the AMI connection setup, the config/options flow, and the sensors.
