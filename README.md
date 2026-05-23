# daikinskyport

Fork of [apetrycki/daikinskyport](https://github.com/apetrycki/daikinskyport) with additional features and fixes.

API and [Home Assistant](https://www.home-assistant.io/) component for accessing a [Daikin One+ Smart Thermostat](https://daikinone.com/) or [Daikin One Lite](https://www.daikinac.com/content/residential/residential-controllers/daikin-one-lite).

Most functions are supported. This was mostly taken from the ecobee code and modified.

## Changes in this fork

- **Schedule setpoints** — per-period climate entities to edit heat/cool setpoints for each enabled schedule period
- **Away settings** — climate entity for away-mode heat/cool setpoints
- **Schedule sensors** — schedule override until and next scheduled temperature
- **Hold/override sync** — improved merging of local changes with cloud state after writes
- **Refresh cloud button** — force a cloud GET and update HA state (diagnostic)
- **Rapid poll after writes** — optional diagnostic switch to poll the cloud every second for 15s after each PUT
- **Logbook** — clearer climate change entries from HA and cloud

## Development

Run unit tests from the repository root (no running Home Assistant instance required):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Tests use lightweight stubs for Home Assistant imports so you do not need a running HA instance or the full `homeassistant` package.

CI runs the same suite on every push and pull request to `master` via [GitHub Actions](.github/workflows/tests.yml).

This fork keeps the upstream repo as `origin` and pushes to a `fork` remote:

```bash
git remote add upstream https://github.com/apetrycki/daikinskyport.git   # once
git fetch upstream
git merge upstream/master
git push fork master
```

Report issues for this fork at [derekjobst/daikinskyport/issues](https://github.com/derekjobst/daikinskyport/issues).

## Installation

This component can be installed via the [Home Assistant Community Store (HACS)](https://hacs.xyz/) or manually.

This integration requires Home Assistant version 2024.02 or later due to changes made in that version that are not backward compatible.

### Install via HACS

_HACS must be [installed](https://hacs.xyz/docs/installation/prerequisites) before following these steps._

1. Log into your Home Assistant instance and open HACS via the sidebar on the left
2. In the HACS menu, open **Integrations**
3. On the integrations page, select the "vertical dots" icon in the top-right corner, and select **Custom repositories**
4. Paste `https://github.com/derekjobst/daikinskyport` into the **Repository** field and select **Integration** in the **Category** menu
5. Click **ADD**
6. Click **+ EXPLORE & DOWNLOAD REPOSITORIES**
7. Select **Daikin Skyport** and click the **DOWNLOAD** button
8. Click **DOWNLOAD**
9. Restart Home Assistant Core via the Home Assistant console by navigating to **Supervisor** in the sidebar on the left, selecting the **System** tab, and clicking **Restart Core**. A restart is necessary in order to load the component.

### Manual Install

_A manual installation is more risky than installation via HACS. You must be familiar with how to SSH into Home Assistant and working in the Linux shell to perform these steps._

1. Download or clone the component's repository by selecting the **Code** button on the [component's GitHub page](https://github.com/derekjobst/daikinskyport).
2. If you downloaded the component as a zip file, extract the file.
3. Copy the `custom_components/daikinskyport` folder from the repository to your Home Assistant `custom_components` folder. Once done, the full path to the component in Home Assistant should be `/config/custom_components/daikinskyport`. The `__init__.py` file (along with the rest of the files) should be directly in the `daikinskyport` folder.

## Usage

In order for this component to talk with your thermostat, the thermostat must be registered with your online Daikin account. If you haven't already done so, follow the instructions for pairing with the mobile app in the [Daikin documentation](https://backend.daikincomfort.com/docs/default-source/product-documents/residential-accessories/other/hg-one-st.pdf?sfvrsn=c0692726_38).

After pairing the thermostat and installing the component, activate the component by going to **Settings**, **Devices & Services**, **Add Integration**, and searching for Daikin Skyport. Enter your email and password at the prompt and optionally a name for your account.

The email and password must be the same ones that you used when you created your account in the mobile app.

Once Core has restarted, navigate to **Configuration** in the sidebar, then **Entities**. Use the search box to search for the name of your thermostat. For example, search for `main room` (the name of your thermostat is shown on the touch screen). You should see a main `climate` entity, `weather`, schedule and away climate entities, and a number of `sensor` entities. Some diagnostic entities (refresh button, rapid poll switch) are disabled by default — enable them in the entity registry if needed.
