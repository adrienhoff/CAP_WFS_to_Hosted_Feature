import requests
import time
import xml.etree.ElementTree as ET
import json
from arcgis.gis import GIS
from arcgis.features import FeatureLayer
from pyproj import Transformer


# Load credentials from config.json
def load_config(config_file):
    with open(config_file, 'r') as f:
        config = json.load(f)
    return config

# Authenticate to ArcGIS
def authenticate_to_gis(portal_url, username, password):
    return GIS(portal_url, username, password)

wfs_url = "https://geoserver.getrave.com/geoserver/Alert_5960563/wfs"
feature_count_params = {
    "service": "WFS",
    "version": "1.1.0",
    "request": "GetFeature",
    "typeName": "Name of WFS",
    "resulttype": "hits"
}
feature_data_params = {
    "service": "WFS",
    "version": "1.1.0",
    "request": "GetFeature",
    "typeName": "Name of WFS",
    "outputFormat": "application/json"
}

# Initialize previous feature count
prev_feature_count = None

# Fetch WFS feature count
def fetch_feature_count():
    response = requests.get(wfs_url, params=feature_count_params)
    response.raise_for_status()  # Raise an exception for HTTP errors
    root = ET.fromstring(response.text)
    return int(root.attrib.get("numberOfFeatures", 0))

# Fetch WFS data
def fetch_wfs_data(wfs_url, feature_data_params):
    response = requests.get(wfs_url, params=feature_data_params)
    response.raise_for_status()  # Raise an exception for HTTP errors
    return response.json()


# Construct the GeoJSON object for the new feature
def construct_geojson(feature):
    coordinates = feature['geometry']['coordinates']
    properties = feature['properties']


    geojson_feature = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": coordinates
        },
        "properties": {
            "alertId": properties.get("alertId"),
            "category": properties.get("category"),
            "certainty": properties.get("certainty"),
            "description": properties.get("description"),
            "event": properties.get("event"),
            "headline": properties.get("headline"),
            "id": properties.get("id"),
            "identifier": properties.get("identifier"),
            "instruction": properties.get("instruction"),
            "scope": properties.get("scope"),
            "severity": properties.get("severity"),
            "status": properties.get("status"),
            "urgency": properties.get("urgency"),
            "uuid": properties.get("uuid")
        }
    }
    return geojson_feature

# Push data to ArcGIS
def push_to_arcgis(geojson_feature, feature_layer):
    # Mapping dictionary for attribute names to column names
    attribute_mapping = {
        "alertId": "alertid",
        "category": "category",
        "certainty": "certainty",
        "description": "description",
        "event": "event",
        "headline": "headline",
        "id": "id",
        "identifier": "identifier",
        "instruction": "instruction",
        "scope": "scope",
        "severity": "severity",
        "status": "status",
        "urgency": "urgency",
        "uuid": "uuid"        
    }
    
    # Convert GeoJSON to the format expected by ArcGIS
    arcgis_feature = {
        "attributes": {},
        "geometry": {
            "rings": geojson_feature["geometry"]["coordinates"],
            "spatialReference": {"wkid": 4326}  
        }
    }

    # Map attributes from GeoJSON to ArcGIS feature using attribute_mapping
    for geojson_attribute, arcgis_column in attribute_mapping.items():
        arcgis_feature["attributes"][arcgis_column] = geojson_feature["properties"].get(geojson_attribute, None)
    
    try:
        # Add new feature
        result = feature_layer.edit_features(adds=[arcgis_feature])
        print("Feature added:", result)
        if result.get('addResults', []) and not result['addResults'][0]['success']:
            print("Error adding feature:", result['addResults'][0]['error'])
    except Exception as e:
        print(f"Error adding feature to ArcGIS: {e}")

    # Optional: Query features and print information for debugging
    query_result = feature_layer.query(where="1=1", out_fields="*")
    for feature in query_result.features:
        print(f"Feature {feature.attributes['objectid']} - alertId: {feature.attributes['alertid']}")


# Delete row from ArcGIS Feature Service
def delete_row(alertId, feature_layer):
    where_clause = f"alertid = '{alertId}'"
    
    # Query the features to delete using the where clause
    features_to_delete = feature_layer.query(where=where_clause).features

    if not features_to_delete:
        print(f"No feature found with alertId {alertId} to delete.")
        return

    object_ids = [feature.attributes['objectid'] for feature in features_to_delete]
    
    result = feature_layer.edit_features(deletes=object_ids)
    print("Row deleted:", result)
    if not result['deleteResults'][0]['success']:
        print("Error deleting row:", result['deleteResults'][0]['error'])

# Load config
config = load_config(r'C:\\Path\\to\\config.json')
gis = authenticate_to_gis(config['portal_url'], config['portal_username'], config['portal_password'])
feature_layer = FeatureLayer('https://url/of/hosted/feature_service', gis)

prev_feature_count = fetch_feature_count()

# Main loop
while True:
    try:
        current_feature_count = fetch_feature_count()
        
        # Fetch WFS data and extract GeoJSON features
        wfs_data = fetch_wfs_data(wfs_url, feature_data_params)
        geojson_features = wfs_data.get('features', [])
        
        # Extract identifiers from GeoJSON features
        geojson_identifiers = {geojson_feature["properties"].get("identifier", None) for geojson_feature in geojson_features}
        
        # Query ArcGIS features
        arcgis_features = feature_layer.query().features
        

        # Extract identifiers from ArcGIS features
        arcgis_identifiers = {feature.attributes.get("identifier") for feature in arcgis_features}

        # Check if there's a change in feature count or identifier
        if (
            prev_feature_count is None 
            or current_feature_count != prev_feature_count 
            or arcgis_identifiers != geojson_identifiers
        ):
            print(f"Previous count: {prev_feature_count}, Current count: {current_feature_count}, GEOJSON Identifiers: {geojson_identifiers}, ESRI Identifiers: {arcgis_identifiers}")
            
            # Delete all existing features from the feature layer
            if arcgis_features:
                for arcgis_feature in arcgis_features:
                    delete_row(arcgis_feature.attributes["alertid"], feature_layer)
                print("Features deleted.")
            
            # Add new features from WFS data
            for feature in geojson_features:
                geojson_feature = construct_geojson(feature)
                push_to_arcgis(geojson_feature, feature_layer)
            print("Repopulated.")
            
            # Update previous feature count
            prev_feature_count = current_feature_count
        else:
            print(f"No change. Current count: {current_feature_count}, GEOJSON Identifiers: {geojson_identifiers}, ESRI Identifiers: {[feature.attributes['identifier'] for feature in arcgis_features]}")
        
    except Exception as e:
        print(f"An error occurred: {e}")

    # Wait for a specified interval before checking again
    time.sleep(60)  # Wait for 1 minute


