# from abc import ABC, abstractmethod
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
import sys
import time
import s3fs


def _process_http_error(http_err, response):
    print(
            f"HTTP error occurred: {http_err}\n"
            f"Status Code: {response.status_code}\n"
            f"Reason: {response.reason}\n"
            f"URL: {response.url}\n"
            f"Response Text: {response.text}"
        )
    
class DataAccess():
    def __init__(self, overlap_url, cropping_url, persist):
        self.token_url = "https://crop.bioscape.io/api/token/"

        self.access_token = None
        try:
            self._load_credentials()
 
        except requests.exceptions.HTTPError as e:
            if  e.response.status_code == 503:
                print("HTTP error occurred: 503 Server Error: Service Temporarily Unavailable")
                sys.exit(1)
            else:
                print(f"An error occurred: {e}")
        except Exception as e:
            print(e) 
        
        if self.access_token is None:
            self._login(persist)
            
        if self.access_token is None:
            raise Exception("User must log in with a valid SMCE username and password!")   
        
        session = requests.session()
        session.headers.update({"Authorization": f'Bearer {self.access_token}'})

        self.URLCROP = cropping_url
        self.URLOVERLAP = overlap_url
        self.URLSTATUS = "https://crop.bioscape.io/api/status/"
        self.URLDOWNLOAD = "https://crop.bioscape.io/api/download/"
        self.session = session

    def _load_credentials(self):
        try:
            netrc_path = os.path.expanduser("~/.netrc")
            username = None
            password = None

            if not os.path.exists(netrc_path):
                raise FileNotFoundError("No .netrc file found.")

            with open(netrc_path, 'r') as f:
                lines = f.readlines()

            credentials_exist = False

            for i, line in enumerate(lines):
                if "machine bioscape" in line:
                    login_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    password_line = lines[i + 2].strip() if i + 2 < len(lines) else ""

                    if login_line.startswith("login"):
                        username = login_line.split(" ")[1]
                    if password_line.startswith("password"):
                        password = " ".join(password_line.split(" ")[1:]) 

                    if username and password:
                        credentials_exist = True
                        break

            if credentials_exist and username and password:
                self.access_token = self._get_access_token(username, password)
            else:
                raise Exception("Credentials not found or invalid.")

        except Exception as e:
            raise Exception(f"An error occurred while loading credentials: {e}")

    def _save_credentials(self, username, password):
        netrc_path = os.path.expanduser("~/.netrc")
        credentials_exist = False

        if os.path.exists(netrc_path):
            with open(netrc_path, 'r') as f:
                lines = f.readlines()

            for i, line in enumerate(lines):
                if "machine bioscape" in line:
                    if i + 1 < len(lines) and f"login {username}" in lines[i + 1]:
                        lines[i + 2] = f"password {password}\n"
                        credentials_exist = True
                        break

            if not credentials_exist:
                    lines.append(f"machine bioscape\n        login {username}\n        password {password}\n")

            with open(netrc_path, 'w') as f:
                f.writelines(lines)

        else:
            with open(netrc_path, 'w') as f:
                f.write(f"machine bioscape\n        login {username}\n        password {password}\n")

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
    
    def _get_overlap(self, geojson, data=None):
        try:
            if data is not None:
                data = {k:v for k, v in data.items() if v is not None}
      
            if isinstance(geojson, gpd.GeoDataFrame):
                geojson_data = json.loads(geojson.to_json())
            else:
                geojson_data = json.loads(gpd.read_file(geojson).to_json())
       
            if data is None:
                data = geojson_data
            else:
                data.update({'geojson':geojson_data})

            response = self.session.post(self.URLOVERLAP, json=data)
            response.raise_for_status()
            return response  
        except HTTPError as http_err:
           _process_http_error(http_err, response)
    
    def _submit_cropping_task(self, geojson, data):
            
        data = {k:v for k, v in data.items() if v is not None}
        
        if isinstance(geojson, gpd.GeoDataFrame):
            geojson_data = json.loads(geojson.to_json())
        else:
            geojson_data = json.loads(gpd.read_file(geojson).to_json())
        
        data.update({"geojson": geojson_data})
        
        response = self.session.post(
            self.URLCROP,
            json=data,
            )
        response.raise_for_status()
        return response.json()['identifier']
    
    def _get_job_status(self, identifier):
        response = self.session.get(os.path.join(self.URLSTATUS, identifier))
        return response.json()['status']

    def _download_data(self, identifier, outpath):
        try:
            url = os.path.join(self.URLDOWNLOAD, identifier)

            if 's3' in outpath:
                fs = s3fs.S3FileSystem(anon=False)
                with fs.open(outpath, 'wb') as s3file:
                    with self.session.get(url, stream=True) as response:
                        response.raise_for_status()
                        for chunk in response.iter_content(chunk_size=16384):
                            s3file.write(chunk)
            else:
                with self.session.get(url, stream=True) as response:
                    response.raise_for_status()
                    with open(outpath, 'wb') as file:
                        for chunk in response.iter_content(chunk_size=16384):
                            file.write(chunk)

        except HTTPError as http_err:
            _process_http_error(http_err, response)
        
    def _load_data(self, identifier, mask_and_scale, engine, verbose=False): 
        try:
            with self.session.get(os.path.join(self.URLDOWNLOAD, identifier), stream=True) as response:
                response.raise_for_status()    
                
                total_size = int(response.headers.get('Content-Length', 0))
                downloaded_size = 0
                
                with io.BytesIO() as byte_stream:
                    for chunk in response.iter_content(chunk_size=1024 * 32):
                        byte_stream.write(chunk)
                        downloaded_size += len(chunk)
                        total_size_mb = total_size / (1024 * 1024)  
                        downloaded_size_mb = downloaded_size / (1024 * 1024) 
                        
                        if total_size > 0:
                            progress = (downloaded_size / total_size) * 100
                            if verbose:
                                print(f"\rLoading Data: {downloaded_size_mb:.2f}/{total_size_mb:.2f} MB ({progress:.2f}%)", end='')

                    byte_stream.seek(0)
               
                    dataset = xr.load_dataset(byte_stream, decode_coords='all', mask_and_scale=mask_and_scale, engine=engine)  
            
            return dataset
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
        super().__init__(
            overlap_url = "https://crop.bioscape.io/api/overlap/", 
            cropping_url = "https://crop.bioscape.io/api/crop/",
            persist = persist
            )
        
    def get_overlap(self, geojson):
        response = super()._get_overlap(geojson)
        gdf = gpd.GeoDataFrame.from_features(response.json()["features"], crs=4326)
        gdf[['flightline','subsection']] = gdf['flightline'].str.split('_',expand=True)
        return gdf
    
    def crop_flightline(self, flightline, subsection, geojson, output_path=None, engine='h5netcdf', mask_and_scale=True, verbose=False):
        if output_path is not None:
            if '.nc' not in output_path:
                raise Exception("Output file path must have a .nc extension!")
        
        data = {
            "flightline": flightline,
            "subsection": subsection, 
            }
        
        identifier = super()._submit_cropping_task(geojson, data) 
        length_of_status = 0

        while True:
            time.sleep(3)
            status = super()._get_job_status(identifier)  
            
            if verbose:
                if len(status) > length_of_status:
                    length_of_status = len(status) 

                status = status.ljust(length_of_status)

                print(f"\r{status}", end='')
          
            if 'Ready' in status or 'Failed' in status:
                break
        
        if 'Ready' in status:
            if verbose:
                print()
            
            if output_path is not None:
                super()._download_data(identifier, output_path)
            else:
                return super()._load_data(identifier, mask_and_scale, engine, verbose)
        elif 'Failed' in status:
            raise Exception(f"{status}")
        else:
            raise Exception(f"{status}")
     
    
    def plot_rgb(data):
        return super()._plot_rgb(data, 'wavelength')
             
class Emit(DataAccess):
    def __init__(self, **kwargs):
        self.edl_token = self._get_edl_token(**kwargs)['access_token']
        
        super().__init__(
            overlap_url = "https://crop.bioscape.io/api/overlapemit/", 
            cropping_url = "https://crop.bioscape.io/api/cropemit/",
            persist = kwargs['persist'] if 'persist' in kwargs else False
            )

    def _get_edl_token(self, **kwargs):
        earthaccess.login(**kwargs)
        return earthaccess.get_edl_token()

    def get_overlap(self, geojson, temporal_range=None, cloud_cover=None):
        data = {
        "access_token": self.edl_token,
        "temporal": temporal_range,
        "cloud_cover": cloud_cover
        }
        response = super()._get_overlap(geojson=geojson, data=data)
        granules =  [DataGranule(res) for res in response.json().get('granules', [])]
        for granule in granules:
            granule.granule_ur = granule['umm']['GranuleUR']
        return granules
    
    def crop_scene(self, granule_ur, geojson, output_path=None ,mask_and_scale=True, engine='scipy', verbose=False):
        if output_path is not None:
            if '.nc' not in output_path:
                raise Exception("Output file path must have a .nc extension!")
        
        data = {
            "access_token": self.edl_token,
            "granule_ur": granule_ur,
            "outpath": output_path
            }
        
        identifier = super()._submit_cropping_task(geojson, data) 
        length_of_status = 0

        while True:
            time.sleep(3)
            status = super()._get_job_status(identifier)  
            
            if verbose:
                if len(status) > length_of_status:
                    length_of_status = len(status) 

                status = status.ljust(length_of_status)

                print(f"\r{status}", end='')
          
            if 'Ready' in status or 'Failed' in status:
                break
        
        if 'Ready' in status:
            if verbose:
                print()
            
            if output_path is not None:
                super()._download_data(identifier, output_path)
            else:
                return super()._load_data(identifier, mask_and_scale, engine, verbose)
            
        elif 'Failed' in status: 
            raise Exception("Cropping Failed. Most likely the AOI contains only No Data values.")
        else:
            raise Exception(f"{status}")
    
    def plot_rgb(data):
        return super()._plot_rgb(data, 'wavelengths')
        