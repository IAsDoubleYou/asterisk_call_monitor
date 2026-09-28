# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-09-28

### Changed

- **Breaking:** `started_at` and `updated_at` are now timezone-aware datetimes instead of raw epoch numbers, so they are actually readable wherever Home Assistant displays an attribute and can be used directly with template filters such as `as_local`, without converting them first. A template that used to do arithmetic on these as numbers needs to use `as_local`/`as_timestamp` instead; see the README for an example.

## [0.3.0] - 2026-09-28

### Added

- The incoming, outgoing and last-call sensors now restore their last known call across a Home Assistant restart, instead of resetting to idle with every attribute `null` until the next real event. Restoring never overrides a call already in progress: it only fills an otherwise idle slot.
- A new `updated_at` attribute reports when a call's status last changed (ringing → answered → ended, for example), separate from `started_at` (when the call began).

### Fixed

- A call that had been going on for over an hour (e.g. a long answered call) could be incorrectly cleared back to idle by the hour-old-call cleanup, because that cleanup measured time since the call *started* rather than since it last *changed*. It now uses the same `updated_at` moment the new attribute reports, so a call that is still actively changing is never pruned, and one that has really gone quiet for an hour is cleared regardless of how long it ran before that.

## [0.2.0] - 2026-09-28

### Changed

- **Breaking:** the call-status sensors' state values changed from Dutch words (`bellen`, `kiezen`, `beantwoord`, `afgewezen`, `bezet`, `niet_beantwoord`, `beeindigd`) to stable English ones (`ringing`, `dialing`, `answered`, `rejected`, `busy`, `no_answer`, `ended`). The sensors are now enum sensors (`device_class: enum`) with a `translation_key`, so the UI shows a label translated into the user's language (English or Dutch) while automations compare against the untranslated English value regardless of language. Any automation comparing a sensor's state to one of the old Dutch words needs updating.

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
