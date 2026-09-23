from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_from_directory
)

from werkzeug.utils import secure_filename

import os
import uuid
import requests
import math


# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)


# =========================================================
# FOLDERS
# =========================================================

UPLOAD_FOLDER = "uploads"

SIMULATION_FOLDER = "simulation_results"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

os.makedirs(SIMULATION_FOLDER, exist_ok=True)


# =========================================================
# OSM SETTINGS
# =========================================================

OSM_HEADERS = {
    "User-Agent": "DamSafe-MVP/1.0"
}


# =========================================================
# FALLBACK DAM DATABASE
#
# This is NOT the complete India database.
# It is only a fallback for important demonstration dams.
# =========================================================

KNOWN_DAMS = [

    {
        "name": "Mettur Dam",
        "lat": 11.7870,
        "lon": 77.8000
    },

    {
        "name": "Sothuparai Dam",
        "lat": 10.13076,
        "lon": 77.46379
    },

    {
        "name": "Vaigai Dam",
        "lat": 9.8565,
        "lon": 77.5003
    },

    {
        "name": "Bhavanisagar Dam",
        "lat": 11.4885,
        "lon": 77.2495
    },

    {
        "name": "Mullaperiyar Dam",
        "lat": 9.5288,
        "lon": 77.1430
    },

    {
        "name": "Krishnagiri Dam",
        "lat": 12.4640,
        "lon": 78.2170
    },

    {
        "name": "Amaravathi Dam",
        "lat": 10.4030,
        "lon": 77.2470
    },

    {
        "name": "Aliyar Dam",
        "lat": 10.4880,
        "lon": 76.9700
    },

    {
        "name": "Papanasam Dam",
        "lat": 8.7060,
        "lon": 77.3690
    },

    {
        "name": "Kallanai",
        "lat": 10.8250,
        "lon": 78.8840
    }
]


# =========================================================
# DISTANCE CALCULATION
# =========================================================

def distance_km(
    lat1,
    lon1,
    lat2,
    lon2
):

    R = 6371.0

    lat1_rad = math.radians(lat1)

    lat2_rad = math.radians(lat2)

    dlat = math.radians(
        lat2 - lat1
    )

    dlon = math.radians(
        lon2 - lon1
    )

    a = (
        math.sin(dlat / 2) ** 2
        +
        math.cos(lat1_rad)
        *
        math.cos(lat2_rad)
        *
        math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a)
    )

    return R * c


# =========================================================
# CHECK BUILT-IN DAM DATABASE
# =========================================================

def check_known_dams(
    latitude,
    longitude
):

    nearest = None

    nearest_distance = float("inf")

    for dam in KNOWN_DAMS:

        distance = distance_km(
            latitude,
            longitude,
            dam["lat"],
            dam["lon"]
        )

        if distance < nearest_distance:

            nearest_distance = distance

            nearest = dam

    # Accept if within approximately 5 km

    if nearest and nearest_distance <= 5:

        return {
            "name": nearest["name"],
            "latitude": nearest["lat"],
            "longitude": nearest["lon"],
            "distance_km": round(
                nearest_distance,
                3
            ),
            "source": "DamSafe fallback database"
        }

    return None


# =========================================================
# SEARCH OPENSTREETMAP FOR NEARBY DAM
# =========================================================

def search_osm_dam(
    latitude,
    longitude
):

    try:

        # Search within approximately 5 km

        radius = 5000

        overpass_url = (
            "https://overpass-api.de/api/interpreter"
        )

        query = f"""
        [out:json][timeout:25];

        (
          node
            ["man_made"="dam"]
            (around:{radius},{latitude},{longitude});

          way
            ["man_made"="dam"]
            (around:{radius},{latitude},{longitude});

          relation
            ["man_made"="dam"]
            (around:{radius},{latitude},{longitude});

          node
            ["waterway"="dam"]
            (around:{radius},{latitude},{longitude});

          way
            ["waterway"="dam"]
            (around:{radius},{latitude},{longitude});
        );

        out center tags;
        """

        response = requests.post(
            overpass_url,
            data=query,
            headers=OSM_HEADERS,
            timeout=30
        )

        if response.status_code != 200:

            return None

        data = response.json()

        elements = data.get(
            "elements",
            []
        )

        if not elements:

            return None

        candidates = []

        for element in elements:

            tags = element.get(
                "tags",
                {}
            )

            name = (
                tags.get("name")
                or
                tags.get("name:en")
                or
                tags.get("name:ta")
                or
                tags.get("official_name")
            )

            if not name:

                continue

            # -----------------------------------------
            # Get coordinates
            # -----------------------------------------

            if (
                "lat" in element
                and
                "lon" in element
            ):

                dam_lat = element["lat"]

                dam_lon = element["lon"]

            elif "center" in element:

                dam_lat = element[
                    "center"
                ].get("lat")

                dam_lon = element[
                    "center"
                ].get("lon")

            else:

                continue

            if (
                dam_lat is None
                or
                dam_lon is None
            ):

                continue

            distance = distance_km(
                latitude,
                longitude,
                dam_lat,
                dam_lon
            )

            candidates.append({

                "name": name,

                "latitude": dam_lat,

                "longitude": dam_lon,

                "distance_km": distance,

                "source": "OpenStreetMap"

            })

        if not candidates:

            return None

        # -----------------------------------------
        # Select nearest named dam
        # -----------------------------------------

        candidates.sort(
            key=lambda x: x["distance_km"]
        )

        result = candidates[0]

        result["distance_km"] = round(
            result["distance_km"],
            3
        )

        return result

    except Exception as e:

        print(
            "OSM dam search error:",
            e
        )

        return None


# =========================================================
# NOMINATIM FALLBACK
# =========================================================

def get_nominatim_name(
    latitude,
    longitude
):

    try:

        url = (
            "https://nominatim.openstreetmap.org/"
            "reverse"
        )

        params = {

            "lat": latitude,

            "lon": longitude,

            "format": "jsonv2",

            "addressdetails": 1,

            "namedetails": 1,

            "zoom": 18

        }

        response = requests.get(

            url,

            params=params,

            headers=OSM_HEADERS,

            timeout=10

        )

        if response.status_code != 200:

            return None

        data = response.json()

        name = (
            data.get("name")
            or
            data.get("display_name")
        )

        if name:

            return {

                "name": name,

                "latitude": latitude,

                "longitude": longitude,

                "distance_km": 0,

                "source": "Nominatim"

            }

        return None

    except Exception as e:

        print(
            "Nominatim error:",
            e
        )

        return None


# =========================================================
# MAIN DAM IDENTIFICATION FUNCTION
# =========================================================

def identify_dam(
    latitude,
    longitude
):

    # -----------------------------------------
    # STEP 1
    # Built-in important dam database
    # -----------------------------------------

    result = check_known_dams(
        latitude,
        longitude
    )

    if result:

        return result


    # -----------------------------------------
    # STEP 2
    # Search nearby OSM dams
    # -----------------------------------------

    result = search_osm_dam(
        latitude,
        longitude
    )

    if result:

        return result


    # -----------------------------------------
    # STEP 3
    # Nominatim fallback
    # -----------------------------------------

    result = get_nominatim_name(
        latitude,
        longitude
    )

    if result:

        return result


    # -----------------------------------------
    # STEP 4
    # Nothing found
    # -----------------------------------------

    return {

        "name":
            "Dam at selected coordinates",

        "latitude":
            latitude,

        "longitude":
            longitude,

        "distance_km":
            0,

        "source":
            "User coordinates"

    }


# =========================================================
# HOME PAGE
# =========================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# =========================================================
# SPH PREVIEW
# =========================================================

@app.route("/sph-preview")
def sph_preview():

    return send_from_directory(

        os.path.join(
            app.root_path,
            SIMULATION_FOLDER
        ),

        "sph_preview.png"

    )


# =========================================================
# SIMULATION API
# =========================================================

@app.route(
    "/api/simulate",
    methods=["POST"]
)
def simulate():

    try:

        # =============================================
        # GET MODEL
        # =============================================

        model = request.form.get(

            "model",

            "Preliminary scenario"

        )


        # =============================================
        # GET LATITUDE
        # =============================================

        try:

            latitude = float(

                request.form.get(
                    "latitude",
                    11.7870
                )

            )

        except:

            return jsonify({

                "error":
                    "Invalid latitude."

            }), 400


        # =============================================
        # GET LONGITUDE
        # =============================================

        try:

            longitude = float(

                request.form.get(
                    "longitude",
                    77.8000
                )

            )

        except:

            return jsonify({

                "error":
                    "Invalid longitude."

            }), 400


        # =============================================
        # VALIDATE COORDINATES
        # =============================================

        if not (
            -90 <= latitude <= 90
        ):

            return jsonify({

                "error":
                    "Latitude must be between -90 and 90."

            }), 400


        if not (
            -180 <= longitude <= 180
        ):

            return jsonify({

                "error":
                    "Longitude must be between -180 and 180."

            }), 400


        # =============================================
        # IDENTIFY DAM
        # =============================================

        dam = identify_dam(

            latitude,

            longitude

        )

        dam_name = dam["name"]


        # =============================================
        # WATER LEVEL
        # =============================================

        try:

            water_level = float(

                request.form.get(
                    "water_level",
                    100
                )

            )

        except:

            return jsonify({

                "error":
                    "Invalid water level."

            }), 400


        if water_level <= 0:

            return jsonify({

                "error":
                    "Water level must be greater than zero."

            }), 400


        # =============================================
        # BREACH WIDTH
        # =============================================

        try:

            breach_width = float(

                request.form.get(
                    "breach_width",
                    50
                )

            )

        except:

            return jsonify({

                "error":
                    "Invalid breach width."

            }), 400


        if breach_width <= 0:

            return jsonify({

                "error":
                    "Breach width must be greater than zero."

            }), 400


        # =============================================
        # SIMULATION TIME
        # =============================================

        try:

            simulation_time = float(

                request.form.get(
                    "simulation_time",
                    6
                )

            )

        except:

            return jsonify({

                "error":
                    "Invalid simulation duration."

            }), 400


        if simulation_time <= 0:

            return jsonify({

                "error":
                    "Simulation duration must be greater than zero."

            }), 400


        # =============================================
        # DEM
        # =============================================

        dem = request.files.get(
            "dem"
        )


        if (
            dem is None
            or
            dem.filename == ""
        ):

            return jsonify({

                "error":
                    "Please upload a DEM file."

            }), 400


        # =============================================
        # CHECK DEM EXTENSION
        # =============================================

        filename = secure_filename(
            dem.filename
        )

        extension = os.path.splitext(
            filename
        )[1].lower()


        if extension not in [
            ".tif",
            ".tiff"
        ]:

            return jsonify({

                "error":
                    "Only .tif or .tiff DEM files are allowed."

            }), 400


        # =============================================
        # SAVE DEM
        # =============================================

        unique_filename = (

            uuid.uuid4().hex[:8]
            + "_"
            + filename

        )

        dem_path = os.path.join(

            UPLOAD_FOLDER,

            unique_filename

        )

        dem.save(
            dem_path
        )


        # =============================================
        # SCENARIO ID
        # =============================================

        scenario_id = (

            "DAM-"
            +
            uuid.uuid4().hex[:8].upper()

        )


        # =============================================
        # DEMO FLOOD POLYGON
        #
        # IMPORTANT:
        # This is still illustrative.
        # It is NOT hydraulic modelling.
        # =============================================

        flood_layer = {

            "type":
                "FeatureCollection",

            "features": [

                {

                    "type":
                        "Feature",

                    "properties": {

                        "scenario_id":
                            scenario_id,

                        "dam_name":
                            dam_name,

                        "model":
                            model,

                        "status":
                            "DEMO SCENARIO"

                    },

                    "geometry": {

                        "type":
                            "Polygon",

                        "coordinates": [[

                            [
                                longitude - 0.025,
                                latitude + 0.018
                            ],

                            [
                                longitude + 0.025,
                                latitude + 0.018
                            ],

                            [
                                longitude + 0.050,
                                latitude - 0.017
                            ],

                            [
                                longitude + 0.020,
                                latitude - 0.052
                            ],

                            [
                                longitude - 0.030,
                                latitude - 0.042
                            ],

                            [
                                longitude - 0.050,
                                latitude - 0.012
                            ],

                            [
                                longitude - 0.025,
                                latitude + 0.018
                            ]

                        ]]

                    }

                }

            ]

        }


        # =============================================
        # RESPONSE
        # =============================================

        return jsonify({

            "status":
                "Scenario generated successfully.",

            "scenario_id":
                scenario_id,

            "dam_name":
                dam_name,

            "dam_latitude":
                dam["latitude"],

            "dam_longitude":
                dam["longitude"],

            "dam_distance_km":
                dam["distance_km"],

            "dam_source":
                dam["source"],

            "model":
                model,

            "latitude":
                latitude,

            "longitude":
                longitude,

            "dem_file":
                unique_filename,

            "water_level":
                water_level,

            "breach_width":
                breach_width,

            "simulation_time":
                simulation_time,

            "warning":
                (
                    "This is a demonstration scenario. "
                    "The displayed polygon is not a "
                    "calculated hydraulic flood prediction."
                ),

            "flood_layer":
                flood_layer

        })


    # =============================================
    # ERROR HANDLING
    # =============================================

    except Exception as e:

        print(
            "Simulation error:",
            e
        )

        return jsonify({

            "error":
                str(e)

        }), 500


# =========================================================
# START FLASK
# =========================================================

if __name__ == "__main__":

    app.run(

        host="127.0.0.1",

        port=5000,

        debug=True

    )