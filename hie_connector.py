import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ConnectorError(RuntimeError):
    pass


SIMULATED_DHIS2_OUTBOX = []


def _post_json(url, payload, bearer_token=None, accept="application/json", timeout=10):
    headers = {
        "Content-Type": "application/fhir+json" if accept.startswith("application/fhir") else "application/json",
        "Accept": accept
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    request = Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            try:
                parsed_body = json.loads(body) if body else None
            except json.JSONDecodeError:
                parsed_body = body[:2000]
            return {
                "status_code": response.status,
                "body": parsed_body
            }
    except HTTPError as error:
        raise ConnectorError(f"Connector returned HTTP {error.code}.") from error
    except URLError as error:
        raise ConnectorError(f"Connector could not reach the configured endpoint: {error.reason}.") from error


def push_fhir_bundle(bundle):
    base_url = os.getenv("HIE_FHIR_BASE_URL", "").rstrip("/")
    if not base_url:
        raise ConnectorError("HIE_FHIR_BASE_URL is not configured.")
    return _post_json(
        f"{base_url}/Bundle",
        bundle,
        bearer_token=os.getenv("HIE_BEARER_TOKEN"),
        accept="application/fhir+json"
    )


def push_dhis2_aggregate(aggregate):
    base_url = os.getenv("DHIS2_BASE_URL", "").rstrip("/")
    if not base_url:
        result = {
            "status": "SIMULATED",
            "endpoint": "local://dhis2-simulator",
            "aggregate": aggregate
        }
        SIMULATED_DHIS2_OUTBOX.append(result)
        return result

    organization_unit = os.getenv("DHIS2_ORG_UNIT")
    data_set = os.getenv("DHIS2_DATA_SET")
    screening_element = os.getenv("DHIS2_SCREENINGS_DATA_ELEMENT")
    closure_element = os.getenv("DHIS2_CLOSURES_DATA_ELEMENT")
    if not all((organization_unit, data_set, screening_element, closure_element)):
        raise ConnectorError(
            "DHIS2_ORG_UNIT, DHIS2_DATA_SET, DHIS2_SCREENINGS_DATA_ELEMENT, "
            "and DHIS2_CLOSURES_DATA_ELEMENT must be configured for live DHIS2 delivery."
        )

    payload = {
        "dataSet": data_set,
        "completeDate": aggregate["period"] + "01",
        "period": aggregate["period"],
        "orgUnit": organization_unit,
        "dataValues": [
            {
                "dataElement": screening_element,
                "period": aggregate["period"],
                "orgUnit": organization_unit,
                "value": str(aggregate["screenings"])
            },
            {
                "dataElement": closure_element,
                "period": aggregate["period"],
                "orgUnit": organization_unit,
                "value": str(aggregate["closures"])
            }
        ]
    }
    result = _post_json(
        f"{base_url}/api/dataValueSets",
        payload,
        bearer_token=os.getenv("DHIS2_BEARER_TOKEN")
    )
    return {"status": "SENT", **result}
