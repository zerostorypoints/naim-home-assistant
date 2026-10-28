# Naim Streaming for Home Assistant

[![HACS custom repository](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![Validate](https://github.com/zerostorypoints/naim-home-assistant/actions/workflows/validate.yml/badge.svg)](https://github.com/zerostorypoints/naim-home-assistant/actions/workflows/validate.yml)
[![Tests](https://github.com/zerostorypoints/naim-home-assistant/actions/workflows/tests.yml/badge.svg)](https://github.com/zerostorypoints/naim-home-assistant/actions/workflows/tests.yml)

Control a Naim network streamer from Home Assistant over your local network: power, volume,
mute, input, playback, now playing and the stream format. No cloud and no account.

> **Brought to you by [HiFiSync](https://hifisync.com/?utm_source=github&utm_medium=readme&utm_campaign=naim_streaming)**, the hi-fi
> recommendation engine grounded in physics, not opinions.
> Check how well your Naim fits your speakers before you buy the next piece.

---

## Features

- **Found automatically.** The streamer announces itself on the network; Home Assistant offers
  to add it. Entering the IP address by hand works too.
- **Instant updates.** The integration follows the streamer's own event stream, so a volume
  change or a new track shows up in Home Assistant within a fraction of a second.
- **Power on and network standby** from Home Assistant, automations and voice assistants.
- **Volume, mute and input**, with the input names you gave them in the Naim app (Analogue 1,
  Digital 1 to 5, CD, Internet Radio, Bluetooth, Spotify and the others your model has).
- **Playback**: play, pause, stop, next, previous, offered while the streamer allows them (it
  says so for each track), with title, artist, album, cover art, input, track length and
  position.
- **Stream format sensors**: audio quality (Hi-Res, CD quality, Lossless, Lossy, DSD), codec,
  sample rate, bit depth, bitrate.
- **Clear off state.** Network standby and "not responding" both show the streamer as off. A
  Network sensor tells them apart, and the entities stay usable after a restart even if the
  streamer is switched off at the mains.
- **Volume limit.** Set a maximum volume so a slipped slider on a phone can never drive the
  system to full power.
- English and Polish translations. Diagnostics download for bug reports.

## Supported streamers

Naim's current streaming platform, the one set up with the
[Naim app](https://www.naimaudio.com/naim-app), shared by the Uniti range, the Mu-so 2nd
generation and the New Classic and 200 series streamers. This integration uses the same local API
as that app.

| Model | Firmware | Status |
|---|---|---|
| Uniti Star | 3.13.0.5828 | Tested |
| Uniti Atom, Uniti Atom HE, Uniti Nova | | Same platform, expected to work, not tested yet |
| Mu-so 2nd generation, Mu-so Qb 2nd generation | | Same platform, expected to work, not tested yet |
| NDX 2, ND5 XS 2, ND 555, NSC 222, NSS 333 | | Same platform, expected to work, not tested yet |

If you own one of the untested models, please
[report whether it works](https://github.com/zerostorypoints/naim-home-assistant/issues/new?template=model_report.yml).

A quick check: if `http://<streamer-address>:15081/system` answers with a page of JSON that
includes `"hardwareType"`, the streamer is on this platform.

Home Assistant may also create a Google Cast and a DLNA player for the same streamer. They see
only their own sessions (a Cast session, a DLNA stream), not what plays from Spotify, Qobuz,
TIDAL or an input, so their state goes stale. Use the player this integration creates.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=zerostorypoints&repository=naim-home-assistant&category=integration)

Or by hand:

1. HACS → ⋮ → **Custom repositories**.
2. Repository `https://github.com/zerostorypoints/naim-home-assistant`, type **Integration**.
3. Install **Naim Streaming** and restart Home Assistant.

### Manual

Copy `custom_components/naim_streaming` into the `custom_components` folder of your Home
Assistant configuration and restart.

Requires Home Assistant 2025.8 or newer.

## Setup

After the restart, Home Assistant lists the streamer under Settings → Devices & services →
**Discovered**. Click **Add**.

If it is not discovered (for example when Home Assistant runs in a separate network or VLAN), go
to Settings → Devices & services → Add integration → **Naim Streaming** and enter the streamer's
IP address.

**Give the streamer a fixed address.** Reserve its IP in your router (a DHCP reservation or
static lease). If the address changes anyway, discovery picks up the new one by itself and Home
Assistant shows a notice under Settings → System → Repairs. Without discovery (another VLAN),
use **Reconfigure** on the integration.

The streamer must be powered at the mains; network standby is enough.

## Entities

For a streamer named `Uniti Star`:

| Entity | What it does |
|---|---|
| `media_player.uniti_star` | Power, volume, mute, input (source), playback, now playing |
| `sensor.uniti_star_audio_quality` | `Hi-Res`, `CD quality`, `Lossless`, `Lossy`, `DSD` while a stream plays |
| `sensor.uniti_star_codec` | As reported by the stream, e.g. `FLAC` |
| `sensor.uniti_star_sample_rate` | kHz, inputs included |
| `sensor.uniti_star_bit_depth` | bit, inputs included |
| `sensor.uniti_star_bitrate` | kbit/s |
| `binary_sensor.uniti_star_network` | On while the streamer answers on the network, standby included |

### Off, standby and not responding

| Situation | Media player | Network |
|---|---|---|
| On | `on` / `playing` / `paused` / `buffering` | on |
| Network standby | `off` | on |
| Switched off at the mains, unplugged, network down | `off` | off |

Turning on from network standby works from Home Assistant. A streamer that does not answer
cannot be woken over the network; the turn-on action then says so.

### Inputs

The input list holds the inputs you can switch to: the physical ones, Internet Radio,
Bluetooth, Spotify, CD. TIDAL, Qobuz, AirPlay and Chromecast start from their own apps, so they
are not in the list, but the media player shows them as the current input while they play.
Inputs disabled in the Naim app are left out; names given there are used.

Audio quality has a value only for a stream that reports its codec (Spotify and Qobuz do, as FLAC).
On a physical input the streamer reports the sample rate and bit depth it receives, but not what
the source behind it plays, so the quality stays empty.

## Options

Settings → Devices & services → Naim Streaming → **Configure**:

- **Maximum volume** (10–100, default 100). Home Assistant never sets the volume above it. The
  Naim app and remote are not limited.
- **Hidden inputs.** Leave inputs out of the input list. Rename inputs in the Naim app; the
  integration uses those names.

Hidden inputs can be chosen once the integration has seen the streamer switched on.

## Examples

Dashboard card:

```yaml
type: media-control
entity: media_player.uniti_star
```

Turntable in the evening:

```yaml
automation:
  - alias: Naim turntable
    triggers:
      - trigger: time
        at: "19:00:00"
    actions:
      - action: media_player.turn_on
        target:
          entity_id: media_player.uniti_star
      - wait_template: "{{ not is_state('media_player.uniti_star', 'off') }}"
        timeout: "00:00:30"
      - action: media_player.volume_set
        target:
          entity_id: media_player.uniti_star
        data:
          volume_level: 0.3
      - action: media_player.select_source
        target:
          entity_id: media_player.uniti_star
        data:
          source: Analogue 1
```

Put the streamer in standby when everyone leaves:

```yaml
automation:
  - alias: Naim off when away
    triggers:
      - trigger: state
        entity_id: zone.home
        to: "0"
    actions:
      - action: media_player.turn_off
        target:
          entity_id: media_player.uniti_star
```

## With DomoSenso

[DomoSenso](https://domosenso.org) is an open framework for building a home on Home Assistant
from tested components, made by the same team
([zerostorypoints/domosenso](https://github.com/zerostorypoints/domosenso) on GitHub). Its
`media` component feeds the music view of the DomoSenso Frame wall tablet from any media player
that meets its contract; it is tested with a Hegel H400 so far.

The catalog does not list a Naim yet, so a scan of your Home Assistant shows the streamer as
unmatched. DomoSenso's
[Integrate a device](https://github.com/zerostorypoints/domosenso/blob/main/docs/integrate-a-device.md)
guide adds one: point the `media` component at `media_player.<your streamer>` from this
integration, not at the Cast or DLNA player.

## Naim on HiFiSync

Components can be checked on HiFiSync before they go into a system: sourced specs, a comparison
with other models, and how well a streamer or amplifier fits your speakers. Naim's range:
[Naim on HiFiSync](https://hifisync.com/brands/naim?utm_source=github&utm_medium=readme&utm_campaign=naim_streaming).

## Troubleshooting

- **Not discovered.** Discovery uses mDNS (`_sues800device._tcp`). It does not cross VLANs
  without an mDNS reflector. Add the streamer by IP address.
- **Shows off although it is on.** Open `http://<streamer-address>:15081/power` from the Home
  Assistant host. If that does not answer, the network path is the problem.
- **Bug reports.** Download diagnostics from the device page and attach them to an
  [issue](https://github.com/zerostorypoints/naim-home-assistant/issues). Debug logging:

  ```yaml
  logger:
    logs:
      custom_components.naim_streaming: debug
  ```

## Security

The streamer's local API has no authentication: anything on your network can control it. This
integration only talks to the streamer on your local network. Keep it off networks you do not
trust.

## How it works

The integration uses the same local API as the Naim app, on port 15081: `/power`,
`/levels/room`, `/nowplaying` and `/inputs` to read and command, and `/notify`, a stream of
server-sent events, for changes. A full refresh runs every 30 seconds as a safety net. The
streamer's id comes from its StreamUnlimited streaming board on port 80
(`systemmanager:systemMember`), the same id it announces over mDNS.

Naim does not document this API. It was read from a Uniti Star; a firmware update may change it.

---

## About HiFiSync

[**HiFiSync**](https://hifisync.com/?utm_source=github&utm_medium=readme&utm_campaign=naim_streaming) is a hi-fi recommendation
engine that scores system synergy with physics instead of adjectives.

- **Match** — what fits the gear you already own.
- **Compare** — component A against component B, by the numbers.
- **Build** — a complete system from scratch in seven steps: topology, then a model for each slot.
- **Synergy score** — a deterministic readout of 21 physics-based checks across Signal, Room and
  Character, each one cited. No brand or dealer can buy a better score.
- **Sourced specs** — every spec links to a primary source, with manufacturer-confirmed and
  secondary data marked apart.
- **Built in Europe** — prices in local currencies and availability checked against EU
  distributors. A catalogue of 1,600+ components from 76 brands.

[Build your system on HiFiSync →](https://hifisync.com/?utm_source=github&utm_medium=readme&utm_campaign=naim_streaming)

## Credits

Made by [Zero Story Points](https://zerostorypoints.com), the team behind HiFiSync.

Not affiliated with or endorsed by Naim Audio Ltd. Naim is a trademark of its owner.

## License

[Apache License 2.0](LICENSE)
