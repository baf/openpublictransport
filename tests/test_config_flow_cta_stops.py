"""Regression tests for #118: telling apart CTA stops that share a name."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.openpublictransport.config_flow import (
    _cta_stop_from_id,
    _stop_dropdown_options,
)
from custom_components.openpublictransport.const import (
    CONF_API_KEY,
    CONF_PROVIDER,
    CONF_STATION_ID,
    DOMAIN,
    PROVIDER_CTA_US,
    PROVIDER_VRR,
)

# The two stops from the issue: both are called "Lawrence & Western".
LAWRENCE_WESTERN = [
    {"id": "bus:3794", "name": "Lawrence & Western", "place": "Chicago"},
    {"id": "bus:3756", "name": "Lawrence & Western", "place": "Chicago"},
]


async def _cta_flow_at_stop_search(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={"entry_type": "departures", CONF_PROVIDER: PROVIDER_CTA_US}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={CONF_API_KEY: "bus-key"})
    assert result["step_id"] == "stop_search"
    return result


def _dropdown_labels(result: dict) -> dict:
    field = next(f for f in result["data_schema"].schema if str(f) == "stop")
    return result["data_schema"].schema[field].container


# -- stop id search --------------------------------------------------------------------


@pytest.mark.parametrize(
    "term, station_id, name",
    [
        ("3794", "bus:3794", "Bus stop 3794"),
        (" 3756 ", "bus:3756", "Bus stop 3756"),
        ("#3794", "bus:3794", "Bus stop 3794"),
        ("03794", "bus:3794", "Bus stop 3794"),
        ("40380", "train:40380", "L station 40380"),
        ("30001", "train:30001", "L station 30001"),
        ("bus:3794", "bus:3794", "Bus stop 3794"),
        ("Train: 40380", "train:40380", "L station 40380"),
    ],
)
def test_cta_stop_ids_are_recognised(term, station_id, name):
    stop = _cta_stop_from_id(term)
    assert stop is not None
    assert (stop["id"], stop["name"], stop["place"]) == (station_id, name, "Chicago")


@pytest.mark.parametrize("term", ["Lawrence & Western", "Clark/Lake", "0", "123456", "bus:", "35th/Archer", ""])
def test_cta_names_are_not_taken_for_ids(term):
    assert _cta_stop_from_id(term) is None


async def test_cta_stop_id_search_skips_the_geocoder(hass: HomeAssistant):
    """The geocoder does not know stop ids, so an id must not be sent there."""
    result = await _cta_flow_at_stop_search(hass)
    with patch("custom_components.openpublictransport.config_flow.get_provider") as mock_gp:
        mock_gp.return_value.search_stops = AsyncMock(return_value=[])
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"stop_search": "3794"}
        )
    mock_gp.return_value.search_stops.assert_not_called()
    assert result["step_id"] == "settings"

    with patch("custom_components.openpublictransport.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_STATION_ID] == "bus:3794"


async def test_numeric_search_still_goes_to_other_providers(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data={"entry_type": "departures", CONF_PROVIDER: PROVIDER_VRR}
    )
    with patch("custom_components.openpublictransport.config_flow.get_provider") as mock_gp:
        mock_gp.return_value.search_stops = AsyncMock(return_value=[{"id": "de:1", "name": "A", "place": "B"}])
        await hass.config_entries.flow.async_configure(result["flow_id"], user_input={"stop_search": "3794"})
    mock_gp.return_value.search_stops.assert_awaited_once_with("3794")


# -- same-named stops in the dropdown --------------------------------------------------


def test_same_named_stops_get_their_id_in_the_label():
    options = _stop_dropdown_options(LAWRENCE_WESTERN, PROVIDER_CTA_US)
    assert options["bus:3794"] == "Lawrence & Western, Chicago (ID 3794)"
    assert options["bus:3756"] == "Lawrence & Western, Chicago (ID 3756)"


def test_unique_labels_are_left_alone():
    stops = [
        {"id": "de:1", "name": "Holthausen", "place": "Düsseldorf"},
        {"id": "de:2", "name": "Holthausen", "place": "Hilden"},
        {"id": "de:3", "name": "Hbf, Düsseldorf", "place": "Düsseldorf"},
    ]
    options = _stop_dropdown_options(stops, PROVIDER_VRR)
    assert options == {
        "__search_again__": "🔍 Neue Suche / New search...",
        "de:1": "Holthausen, Düsseldorf",
        "de:2": "Holthausen, Hilden",
        "de:3": "Hbf, Düsseldorf",
    }


def test_other_providers_show_their_raw_id_for_duplicates():
    stops = [{"id": "de:1", "name": "Markt", "place": "X"}, {"id": "de:2", "name": "Markt", "place": "X"}]
    options = _stop_dropdown_options(stops, PROVIDER_VRR)
    assert options["de:1"] == "Markt, X (ID de:1)"
    assert options["de:2"] == "Markt, X (ID de:2)"


async def test_cta_stop_select_tells_same_named_stops_apart(hass: HomeAssistant):
    result = await _cta_flow_at_stop_search(hass)
    with patch("custom_components.openpublictransport.config_flow.get_provider") as mock_gp:
        mock_gp.return_value.search_stops = AsyncMock(return_value=LAWRENCE_WESTERN)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"stop_search": "Lawrence & Western, Chicago"}
        )
    assert result["step_id"] == "stop_select"
    labels = _dropdown_labels(result)
    assert labels["bus:3794"] != labels["bus:3756"]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={"stop": "bus:3756"})
    assert result["step_id"] == "settings"
    with patch("custom_components.openpublictransport.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})
    assert result["data"][CONF_STATION_ID] == "bus:3756"
