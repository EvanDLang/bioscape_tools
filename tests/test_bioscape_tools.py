import pytest
from bioscape_tools import Bioscape, Emit
import xarray as xr
import os
import geopandas as gpd
import s3fs

geojson = 'tests/test.geojson'
s3_path = 's3://bioscape-smce-user-bucket/edlang/test.nc'

@pytest.fixture
def bioscape_instance():
    return Bioscape()

@pytest.fixture
def emit_instance():
    return Emit()

@pytest.fixture
def bioscape_files(bioscape_instance):
    return bioscape_instance.get_overlap(geojson)

@pytest.fixture
def bioscape_files_gdf(bioscape_instance):
    return bioscape_instance.get_overlap(gpd.read_file(geojson))

@pytest.fixture
def emit_files(emit_instance):
    return emit_instance.get_overlap(geojson, temporal_range=("2024-01-01", "2024-10-01"), cloud_cover=(0,10))

@pytest.fixture
def emit_files_gdf(emit_instance):
    return emit_instance.get_overlap(gpd.read_file(geojson), temporal_range=("2024-01-01", "2024-10-01"), cloud_cover=(0,10))

def test_bioscape_get_overlap(bioscape_files):
    assert isinstance(bioscape_files, gpd.GeoDataFrame)
    assert len(bioscape_files) == 5  

def test_bioscape_crop_flightline(bioscape_instance, bioscape_files):
    flightline, subsection = bioscape_files.iloc[0]['flightline'], bioscape_files.iloc[0]['subsection']
    result = bioscape_instance.crop_flightline(flightline, subsection, geojson)
    assert isinstance(result, xr.Dataset)

def test_bioscape_crop_flightline_to_file(bioscape_instance, bioscape_files):
    flightline, subsection = bioscape_files.iloc[0]['flightline'], bioscape_files.iloc[0]['subsection']
    bioscape_instance.crop_flightline(flightline, subsection, geojson, output_path='test.nc')
    assert os.path.exists('test.nc')
    os.unlink('test.nc')
    
def test_bioscape_crop_flightline_to_s3(bioscape_instance, bioscape_files):
    s3 = s3fs.S3FileSystem(anon=False)
    flightline, subsection = bioscape_files.iloc[0]['flightline'], bioscape_files.iloc[0]['subsection']
    bioscape_instance.crop_flightline(flightline, subsection, geojson, output_path=s3_path)
    assert s3.exists(s3_path)
    s3.delete(s3_path)

def test_emit_get_overlap(emit_files):
    assert len(emit_files) > 0
    assert hasattr(emit_files[0], 'granule_ur')

def test_emit_crop_scene(emit_instance, emit_files):
    result = emit_instance.crop_scene(emit_files[0].granule_ur, geojson)
    assert isinstance(result, xr.Dataset)
    
def test_emit_crop_scene_to_file(emit_instance, emit_files):
    emit_instance.crop_scene(emit_files[0].granule_ur, geojson, output_path='test.nc')
    assert os.path.exists('test.nc')
    os.unlink('test.nc')
    
def test_emit_crop_scene_to_s3(emit_instance, emit_files):
    s3 = s3fs.S3FileSystem(anon=False)
    emit_instance.crop_scene(emit_files[0].granule_ur, geojson, output_path=s3_path)
    assert s3.exists(s3_path)
    s3.delete(s3_path)