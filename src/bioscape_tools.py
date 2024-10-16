
from abc import ABC, abstractmethod
import requests
from requests.exceptions import HTTPError
import earthaccess
from earthaccess.results import DataGranule
import xarray as xr
import io
import matplotlib.pyplot as plt
import numpy as np
import netrc
import os
import json
import getpass
import geopandas as gpd


def _process_http_error(http_err, response):
    print(
            f"HTTP error occurred: {http_err}\n"
            f"Status Code: {response.status_code}\n"
            f"Reason: {response.reason}\n"
            f"URL: {response.url}\n"
            f"Response Text: {response.text}"
        )
    
class DataAccess(ABC):
    def __init__(self, overlap_url, cropping_url, session):
        self.URLCROP = cropping_url
        self.URLOVERLAP = overlap_url
        self.session = session
        
    @abstractmethod
    def _get_access_token():
        pass    
    
    def _get_overlap(self, geojson, data=None):
        try:
            if data is not None:
                data = {k:v for k, v in data.items() if v is not None}
      
            with open(geojson) as f:
                geojson_data = json.load(f)
                
            if data is None:
                data = geojson_data
            else:
                data.update({'geojson':geojson_data})

            response = self.session.post(self.URLOVERLAP, json=data)
            response.raise_for_status()
            return response  
        except HTTPError as http_err:
           _process_http_error(http_err, response)
    
    def _crop_data(self, geojson, data, output_path, mask_and_scale=True):
        try:
            if output_path is not None:
                assert '.nc' in output_path, "Output path must have a .nc file extension!"
            
            data = {k:v for k, v in data.items() if v is not None}
            
            with open(geojson) as f:
                geojson_data = json.load(f)

            data.update({"geojson": geojson_data})
            
            response = self.session.post(
                self.URLCROP,
                json=data,
                )
            response.raise_for_status() 
            if output_path is not None:
                with open(output_path, 'wb') as f:
                    f.write(response.content)
            else:
                return xr.open_dataset(io.BytesIO(response.content),decode_coords='all', mask_and_scale=mask_and_scale, engine='h5netcdf')   
        except HTTPError as http_err:
           _process_http_error(http_err, response)
    
    def _plot_rgb(self, data, band_name):
        rgb_image = np.stack([
            data.sel(**{band_name: 650}, method='nearest').reflectance.values,
            data.sel(**{band_name: 560}, method='nearest').reflectance.values,
            data.sel(**{band_name: 470}, method='nearest').reflectance.values,
        ], axis=-1)

        plt.imshow(rgb_image)
        plt.axis('off')
        plt.show()
        
class Bioscape(DataAccess):
    def __init__(self, persist=False):
        self.token_url = "https://crop.bioscape.io/token/"

        self.access_token = None
        try:
            self._load_credentials()
        except:
            pass
        if self.access_token is None:
            self._login(persist)
            
        if self.access_token is None:
            raise Exception("User must log in with a valid SMCE username and password!")   
        
        session = requests.session()
        session.headers.update({"Authorization": f'Bearer {self.access_token}'})
        super().__init__(
            overlap_url = "https://crop.bioscape.io/overlap/", 
            cropping_url = "https://crop.bioscape.io/crop/",
            session=session
            )
    def _load_credentials(self):
        try:
            netrc_path = os.path.expanduser("~/.netrc")
            username = None
            password = None
            if not os.path.exists(netrc_path):
                raise FileNotFoundError("No .netrc file found.")

            username, _, password = netrc.netrc(netrc_path).authenticators("bioscape")
            if username is not None and password is not None:
                self.access_token = self._get_access_token(username, password)
            else:
                raise Exception
        except Exception as e:
            pass

    def _save_credentials(self, username, password):
        netrc_path = os.path.expanduser("~/.netrc")
        credentials_exist = False

 
        if os.path.exists(netrc_path):
            with open(netrc_path, 'r') as f:
                for line in f:
                    if f"machine bioscape" in line and f"login {username}" in next(f, ''):
                        credentials_exist = True
                        break

        if not credentials_exist:
            with open(netrc_path, 'a') as f:
                f.write(f"machine bioscape\nlogin {username}\npassword {password}\n")

    def _login(self, persist=False):
        username = input("Enter your SMCE username: ")
        password = getpass.getpass("Enter your SMCE password: ")
        
        self.access_token = self._get_access_token(username, password)
        
        if persist and self.access_token is not None:
            self._save_credentials(username, password)
      
    def _get_access_token(self, username, password):
        try:
            response = requests.post(
                self.token_url,
                data={"username": username, "password": password},
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            response.raise_for_status()  
            return response.json().get('access_token')
        except HTTPError as http_err:
           _process_http_error(http_err, response)
           return None
    
    def get_overlap(self, geojson):
        response = super()._get_overlap(geojson)
        gdf = gpd.GeoDataFrame.from_features(response.json()["features"], crs=4326)
        gdf[['flightline','subsection']] = gdf['flightline'].str.split('_',expand=True)
        return gdf
    
    # remove write file and just set output_path to none. if output file is none, pass output.nc else write file and pass provided outpath
    def __crop_data(self, flightline, subsection, geojson, output_path=None, mask_and_scale=True):
      

        data = {
            "flightline": flightline,
            "subsection": subsection, 
            "outpath": output_path
            }
        
        return super()._crop_data(geojson, data, output_path, mask_and_scale)
    
    def crop_flightline(self, flightline, subsection, geojson, output_path=None, mask_and_scale=True):
        return self.__crop_data(flightline, subsection, geojson, output_path, mask_and_scale)
    
    def plot_rgb(data):
        return super()._plot_rgb(data, 'wavelength')
             
class Emit(DataAccess):
    def __init__(self, **kwargs):
        self.access_token = self._get_access_token(**kwargs)['access_token']
        session = requests.session()
        super().__init__(
            overlap_url = "https://crop.bioscape.io/overlapemit/", 
            cropping_url = "https://crop.bioscape.io/cropemit/",
            session = session
            )

    def _get_access_token(self, **kwargs):
        earthaccess.login(**kwargs)
        return earthaccess.get_edl_token()

    def get_overlap(self, geojson, temporal_range=None, cloud_cover=None):
        data = {
        "access_token": self.access_token,
        "temporal": temporal_range,
        "cloud_cover": cloud_cover
        }
        response = super()._get_overlap(geojson=geojson, data=data)
        granules =  [DataGranule(res) for res in response.json().get('granules', [])]
        for granule in granules:
            granule.granule_ur = granule['umm']['GranuleUR']
        return granules
    
    def __crop_data(self, granule_ur, geojson, output_path=None, mask_and_scale=True):
           
        data = {
            "access_token": self.access_token,
            "granule_ur": granule_ur,
            "outpath": output_path
            }
        
        return super()._crop_data(geojson, data, output_path, mask_and_scale)
    
    def crop_scene(self, granule_ur, geojson, output_path=None,mask_and_scale=True):
        return self.__crop_data(granule_ur, geojson, output_path, mask_and_scale)
    
    def plot_rgb(data):
        return super()._plot_rgb(data, 'wavelengths')
        