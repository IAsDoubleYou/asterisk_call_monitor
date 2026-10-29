# <img src="https://raw.githubusercontent.com/IAsDoubleYou/asterisk_call_monitor/main/custom_components/asterisk_call_monitor/brand/icon.png" height="48"> Asterisk Call Monitor for Home Assistant

[![HACS Custom][hacs_shield]][hacs]
[![GitHub Latest Release][releases_shield]][latest_release]
[![GitHub Downloads (latest Release)][downloads_latest_shield]][latest_release]
[![GitHub All Releases][downloads_total_shield]][releases]
[![Tests][tests_shield]][tests]

A Home Assistant custom integration that connects directly to an Asterisk PBX over the **Asterisk Manager Interface (AMI)** and tracks the current incoming and outgoing call, so automations can react to a ringing or dialing phone without a separate script or an MQTT hop in between.

## Why this exists

Detecting "who is calling right now" and "what number are we dialing right now" from Asterisk's AMI event stream is fiddly: the interesting information is spread across several event types (`Newchannel`, `Newexten`, `Dial`, `Hangup`, `BridgeEnter`/`DialAnswer`), and telling a real external call apart from an internal handset, or a rejected call from a busy signal, takes some care. This integration does that classification once, centrally, and exposes the result as three sensors instead of every automation having to reason about raw AMI events (or a hand-rolled script publishing to MQTT) itself.

## Features

* **Incoming call sensor** — the status of the current incoming call (ringing, answered, rejected, busy, not answered, ended) with the caller's number.
* **Outgoing call sensor** — the same, for the current outgoing call (dialing instead of ringing).
* **Last call sensor** — whichever of the two changed most recently, with a `direction` attribute, so an automation that only cares about "the last thing that happened" does not need to watch two entities.
* Push-driven: sensors update the instant an AMI event arrives, no polling.
* Distinguishes an internal handset from a real external caller/destination, and reports why a call ended (rejected before pickup, busy, not answered, or a normal hangup after being answered) instead of a single generic "ended" status.
* Reconnects automatically if the AMI connection drops, and clears a call that is still ringing/dialing/answered after an hour without changing (e.g. a missed `Hangup` event). A call that already ended keeps showing as the last known call indefinitely, across restarts included, until the next one replaces it.
* Survives a Home Assistant restart: each sensor restores its last known call so the dashboard is not blank until the next real one, and the shared call tracker never mistakes stale, restored data for one still in progress.

## Requirements

Home Assistant 2026.3.0 or newer (Python 3.14), declared as the minimum in `hacs.json`.

## Installation

### Via [HACS](https://hacs.xyz/)

This integration is not in the HACS default store. Add it as a custom repository:

1. HACS → the **⋮** menu → **Custom repositories**.
2. Repository: `https://github.com/IAsDoubleYou/asterisk_call_monitor`, category **Integration**.
3. Install **Asterisk Call Monitor**, then restart Home Assistant.

### Manual

1. Copy `custom_components/asterisk_call_monitor` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## Configuration

Settings → Devices & Services → **+ Add Integration** → search for **Asterisk Call Monitor**.

| Field | Required | Default | Description |
|---|---|---|---|
| Host | yes | | Host name or IP address of the Asterisk server. |
| Port | no | `5038` | Port the AMI listens on. |
| Username | yes | | AMI username, as configured in `manager.conf`. |
| Password | yes | | AMI secret for that user. |

The connection is tested before it is saved. AMI credentials need at least the `system`, `call` and `originate` read privileges to receive the events this integration listens for.

### Options

Available afterwards via **Configure** on the integration card:

| Option | Default | Description |
|---|---|---|
| Internal extensions | `100` | Comma separated list of the household's own handsets. A ringing channel from one of these is never reported as an incoming call, one is never reported as an outgoing call's destination either, and - the other way around - only a dialplan step happening on one of these extensions' own channels is trusted to be the start of an outgoing call in the first place. That last part matters because an incoming call's own dialplan traversal produces the same kind of steps a real outgoing call does (ringing a handset via `Dial()`, or a step whose "Extension" is the dialed DID), just on a channel that never belongs to a real extension. |
| Minimum digits for an external number | `5` | An extension dialed without a clearer `Dial` event to name the destination is only treated as an outgoing call once it has at least this many digits. |
| Country of the phone system | Home Assistant's country | The country the phone numbers belong to, used to tell a national number from an international one (see [Phone number formats](#phone-number-formats)). Leave empty to use the country set in Home Assistant. |

## Sensors

Each sensor's state is the current call status; the phone number (as received and in a uniform national and international form), when the call started, when it last changed status, and (once it has ended) the hangup cause are exposed as attributes.

Sensors are enum sensors: the state shown in the UI is translated into the frontend's language (English by default, Dutch included), while automations always compare against the stable, untranslated value in the table below regardless of language.

`started_at` and `updated_at` are timezone-aware datetimes (UTC), not epoch numbers, so they display sensibly wherever Home Assistant already knows how to show a timestamp, and work directly with template filters such as `as_local`. For a specific display format, for example on a dashboard card:

```jinja
{{ as_local(state_attr('sensor.asterisk_..._incoming_call', 'updated_at')).strftime('%d-%m-%Y %H:%M:%S') }}
```

| Status | Meaning |
|---|---|
| `idle` | No active call in this direction right now. |
| `ringing` | An incoming call is ringing. |
| `dialing` | An outgoing call is being dialed. |
| `answered` | The call was answered. |
| `rejected` | The call was hung up before it was answered. |
| `busy` | The destination was busy. |
| `no_answer` | The call was not answered in time. |
| `ended` | The call was answered and then hung up normally. |

## Phone number formats

The `phonenumber` attribute holds the number exactly as Asterisk reports it, and that is not uniform. FreePBX hands over an incoming caller as it received it from the provider, usually in national notation (`0123456789`), but it returns the destination of an outgoing call as the dialplan sends it to the trunk, usually in international notation (`0031123456789`). That depends on the outbound routes of your dialplan and can differ per dialplan, so the integration cannot rely on either one. Looking a number up in a contact list or a database then only works for one of the two directions.

To get a uniform format, every sensor also has these attributes, calculated from `phonenumber`:

| Attribute | Example | Description |
|---|---|---|
| `phonenumber_national` | `0123456789` | Digits only, including the national trunk prefix. |
| `phonenumber_international` | `+31123456789` | The international [E.164](https://en.wikipedia.org/wiki/E.164) notation. |

Both attributes read the number against the country of the phone system: the **Country of the phone system** option, or the country set in Home Assistant when that is empty. Without a country, a number in international notation (`+` or `00`) still gets its `phonenumber_international`, but a national number cannot be read, so both attributes stay empty. `phonenumber_national` is also empty for a number from another country than the phone system's, because its national notation would be meaningless next to local numbers. Anything that is not a plausible phone number, such as an internal extension, a short code like `112` or `anonymous`, leaves both attributes empty; `phonenumber` itself is never changed.

Phone number parsing uses the [phonenumbers](https://pypi.org/project/phonenumbers/) library, which Home Assistant installs for you.

## Troubleshooting

* **"Could not reach the Asterisk server"** — check the host, port and that the AMI is reachable from the Home Assistant host (`manager.conf`'s `bindaddr` and `permit`/`deny` rules commonly block this).
* **"The AMI refused the username or password"** — check the AMI user's credentials and that it has the event privileges mentioned above.
* **`phonenumber_national` or `phonenumber_international` is empty** — check the country under Configure (or in Home Assistant's general settings); a national number cannot be read without one. See [Phone number formats](#phone-number-formats).
* An incoming call from an internal handset showing up as a caller, or the reverse — adjust **Internal extensions** / **Minimum digits for an external number** under Configure.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE)

[hacs_shield]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square
[hacs]: https://github.com/hacs/integration
[latest_release]: https://github.com/IAsDoubleYou/asterisk_call_monitor/releases/latest
[releases_shield]: https://img.shields.io/github/v/release/IAsDoubleYou/asterisk_call_monitor?style=flat-square
[releases]: https://github.com/IAsDoubleYou/asterisk_call_monitor/releases/
[downloads_total_shield]: https://img.shields.io/github/downloads/IAsDoubleYou/asterisk_call_monitor/total?style=flat-square
[downloads_latest_shield]: https://img.shields.io/github/downloads/IAsDoubleYou/asterisk_call_monitor/latest/total?style=flat-square
[tests_shield]: https://img.shields.io/github/actions/workflow/status/IAsDoubleYou/asterisk_call_monitor/tests.yaml?branch=main&label=tests&style=flat-square
[tests]: https://github.com/IAsDoubleYou/asterisk_call_monitor/actions/workflows/tests.yaml
