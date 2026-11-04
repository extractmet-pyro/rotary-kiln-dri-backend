# Example requests (FICTIONAL values for API validation - not operating recommendations)
* `simulation_request_moisture.json` -> `POST /api/v1/simulations`
* `mpc_request.json` -> `POST /api/v1/mpc/recommend`

    curl -X POST localhost:8000/api/v1/simulations -H 'Content-Type: application/json' -d @examples/simulation_request_moisture.json
