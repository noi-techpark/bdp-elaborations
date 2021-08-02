import requests
import os
import logging
from model.Dtos import Provenance
from ODHKeyCloakClient import KeycloakClient

log = logging.getLogger()

class DataPusher:
    def __init__(self):
        self.provenance_id = None
        self.token = KeycloakClient.getDefaultInstance().token("", "","client_credentials")
        self.upsert_provenance()

    def send_data(self,station_type, data_map):
        data_map["provenance"]= self.provenance_id
        endpoint = os.getenv("ODH_SHARE_ENDPOINT")+"/json/pushRecords/" + station_type
        log.debug("Data send to writer: " + str(data_map))
        r = requests.post(endpoint, json=data_map, headers={"Authorization" : "Bearer " + self.token['access_token']})
        if (r.status_code != 201):
            log.warn("Status code not 201 but " + str(r.status_code))
            log.warn(data_map)
    
    def upsert_provenance(self):
        collector = os.getenv("PROVENANCE_NAME")
        log.debug("Provenance name: " + collector)
        version = os.getenv("PROVENANCE_VERSION")
        log.debug("Provenance verison: " + version)
        lineage = os.getenv("PROVENANCE_LINEAGE")
        log.debug("Provenance lineage: " + lineage)
        p = Provenance(None, lineage, collector, version)
        r = requests.post(os.getenv("ODH_SHARE_ENDPOINT")+"/json/provenance", json= p, headers={"Authorization" : "Bearer " + self.token['access_token']})
        self.provenance_id = r.text
