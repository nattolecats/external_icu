# Copyright 2017 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Utility methods associated with ICU source and builds."""

from __future__ import print_function

import filecmp
import glob
import os
import pathlib
import shutil
import subprocess
import sys

import i18nutil
import ziputil


# See https://github.com/unicode-org/icu/blob/main/docs/userguide/icu_data/buildtool.md
# for the documentation.
ICU_DATA_FILTERS = """{
  "featureFilters": {
    "misc": {
      "excludelist": [
        "metaZones",
        "timezoneTypes",
        "windowsZones",
        "zoneinfo64"
      ]
    },
    "brkitr_adaboost": {
      "includelist": [
        "jaml"
      ]
    }
  }
}
"""

ICU_MLDATA_FILTERS = """{
  "featureFilters": {
    "brkitr_adaboost": {
      "includelist": [
        "jaml"
      ]
    }
  }
}
"""


def cldrDir():
  """Returns the location of CLDR in the Android source tree."""
  android_build_top = i18nutil.GetAndroidRootOrDie()
  cldr_dir = os.path.realpath('%s/external/cldr' % android_build_top)
  i18nutil.CheckDirExists(cldr_dir, 'external/cldr')
  return cldr_dir


def icuDir():
  """Returns the location of ICU in the Android source tree."""
  android_build_top = i18nutil.GetAndroidRootOrDie()
  icu_dir = os.path.realpath('%s/external/icu' % android_build_top)
  i18nutil.CheckDirExists(icu_dir, 'external/icu')
  return icu_dir


def icu4cDir():
  """Returns the location of ICU4C in the Android source tree."""
  icu4c_dir = os.path.realpath('%s/icu4c/source' % icuDir())
  i18nutil.CheckDirExists(icu4c_dir, 'external/icu/icu4c/source')
  return icu4c_dir


def icu4jDir():
  """Returns the location of ICU4J in the Android source tree."""
  icu4j_dir = os.path.realpath('%s/icu4j' % icuDir())
  i18nutil.CheckDirExists(icu4j_dir, 'external/icu/icu4j')
  return icu4j_dir


def datFile(icu_build_dir):
  """Returns the location of the ICU .dat file in the specified ICU build dir."""
  dat_file_pattern = '%s/data/out/tmp/icudt??l.dat' % icu_build_dir
  dat_files = glob.glob(dat_file_pattern)
  if len(dat_files) != 1:
    print('ERROR: Unexpectedly found %d .dat files (%s). Halting.' % (len(datfiles), datfiles))
    sys.exit(1)
  dat_file = dat_files[0]
  return dat_file


def PrepareIcuBuild(icu_build_dir, data_filters_json=None):
  """Sets up an ICU build in the specified directory.

  Creates the directory and runs "runConfigureICU Linux"
  """
  # Keep track of the original cwd so we can go back to it at the end.
  original_working_dir = os.getcwd()

  # Create a directory to run 'make' from.
  if not os.path.exists(icu_build_dir):
    os.mkdir(icu_build_dir)
  os.chdir(icu_build_dir)

  # Build the ICU tools.
  print('Configuring ICU tools...')
  cmd = ['env']
  if data_filters_json is not None:
    json_file_path = os.path.join(icu_build_dir, "icu4c_data_filters.json")
    print("json path: %s" % json_file_path)
    writeFileContent(json_file_path, data_filters_json)
    cmd.append('ICU_DATA_FILTER_FILE=%s' % json_file_path)

  cmd += ['ICU_DATA_BUILDTOOL_OPTS=--include_uni_core_data',
          '%s/runConfigureICU' % icu4cDir(),
          'Linux']
  subprocess.check_call(cmd)

  os.chdir(original_working_dir)

def writeFileContent(file_path, file_content):
  """Write a string into the file"""
  with open(file_path, "w") as file:
    file.write(file_content)

def MakeTzDataFiles(icu_build_dir, iana_tar_file):
  """Builds and runs the ICU tools in ${icu_Build_dir}/tools/tzcode.

  The tools are run against the specified IANA tzdata .tar.gz.
  The resulting zoneinfo64.txt is copied into the src directories.
  """
  tzcode_working_dir = '%s/tools/tzcode' % icu_build_dir

  # Fix missing files.
  # The tz2icu tool only picks up icuregions and icuzones if they are in the CWD
  for icu_data_file in [ 'icuregions', 'icuzones']:
    icu_data_file_source = '%s/tools/tzcode/%s' % (icu4cDir(), icu_data_file)
    icu_data_file_symlink = '%s/%s' % (tzcode_working_dir, icu_data_file)
    os.symlink(icu_data_file_source, icu_data_file_symlink)

  iana_tar_filename = os.path.basename(iana_tar_file)
  working_iana_tar_file = '%s/%s' % (tzcode_working_dir, iana_tar_filename)
  shutil.copyfile(iana_tar_file, working_iana_tar_file)

  print('Making ICU tz data files...')
  # The Makefile assumes the existence of the bin directory.
  os.mkdir('%s/bin' % icu_build_dir)

  # -j1 is needed because the build is not parallelizable. http://b/109641429
  subprocess.check_call(['make', '-j1', '-C', tzcode_working_dir])

  # Copy the source file to its ultimate destination.
  zoneinfo_file = '%s/zoneinfo64.txt' % tzcode_working_dir
  icu_txt_data_dir = '%s/data/misc' % icu4cDir()
  print('Copying zoneinfo64.txt to %s ...' % icu_txt_data_dir)
  shutil.copy(zoneinfo_file, icu_txt_data_dir)


def MakeAndCopyIcuDataFiles(icu_build_dir, copy_icu4c_dat_file_only=False):
  """Builds the ICU .dat and .jar files using the current src data.

  The files are copied back into the expected locations in the src tree.

  This is a low-level method.
  Please check :func:`GenerateIcuDataFiles()` for caveats.
  """
  # Keep track of the original cwd so we can go back to it at the end.
  original_working_dir = os.getcwd()

  # Regenerate the .dat file.
  os.chdir(icu_build_dir)
  subprocess.check_call(['make', '-j32'])

  # Copy the .dat file to its ultimate destination.
  icu_dat_data_dir = '%s/stubdata' % icu4cDir()
  dat_file = datFile(icu_build_dir)

  print('Copying %s to %s ...' % (dat_file, icu_dat_data_dir))
  shutil.copy(dat_file, icu_dat_data_dir)

  if copy_icu4c_dat_file_only:
    return

  # Generate the ICU4J .jar files
  subprocess.check_call(['make', '-j32', 'icu4j-data'])

  # Generate the test data in icu4c/source/test/testdata/out
  subprocess.check_call(['make', '-j32', 'tests'])

  # Copy the ICU4J .jar files to their ultimate destination.
  icu_jar_data_dir = '%s/main/shared/data' % icu4jDir()
  jarfiles = glob.glob('data/out/icu4j/*.jar')
  if len(jarfiles) != 3:
    print('ERROR: Unexpectedly found %d .jar files (%s). Halting.' % (len(jarfiles), jarfiles))
    sys.exit(1)
  for jarfile in jarfiles:
    icu_jarfile = os.path.join(icu_jar_data_dir, os.path.basename(jarfile))
    if ziputil.ZipCompare(jarfile, icu_jarfile):
      print('Ignoring %s which is identical to %s ...' % (jarfile, icu_jarfile))
    else:
      print('Copying %s to %s ...' % (jarfile, icu_jar_data_dir))
      shutil.copy(jarfile, icu_jar_data_dir)

  testdata_out_dir = '%s/test/testdata/out' % icu4cDir()
  print('Copying test data to %s ' % testdata_out_dir)
  if os.path.exists(testdata_out_dir):
    shutil.rmtree(testdata_out_dir)
  shutil.copytree('test/testdata/out', testdata_out_dir)

  # Switch back to the original working cwd.
  os.chdir(original_working_dir)


def MakeAndCopyOverlayTzIcuData(icu_build_dir, dest_file):
  """Makes a .dat file containing just time-zone data.

  The overlay file can be used as an overlay of a full ICU .dat file
  to provide newer time zone data. Some strings like translated
  time zone names will be missing, but rules will be correct.
  """

  # Keep track of the original cwd so we can go back to it at the end.
  original_working_dir = os.getcwd()

  # Regenerate the .res files.
  os.chdir(icu_build_dir)
  subprocess.check_call(['make', '-j32'])

  # The list of ICU resources needed for time zone data overlays.
  tz_res_names = [
          'metaZones.res',
          'timezoneTypes.res',
          'windowsZones.res',
          'zoneinfo64.res',
  ]

  dat_file = datFile(icu_build_dir)
  icu_package_dat = os.path.basename(dat_file)
  if not icu_package_dat.endswith('.dat'):
      print('%s does not end with .dat' % icu_package_dat)
      sys.exit(1)
  icu_package = icu_package_dat[:-4]

  # Create a staging directory to hold the files to go into the overlay .dat
  res_staging_dir = '%s/overlay_res' % icu_build_dir
  os.mkdir(res_staging_dir)

  # Copy all the .res files we need from, e.g. ./data/out/build/icudt55l, to the staging directory
  res_src_dir = '%s/data/out/build/%s' % (icu_build_dir, icu_package)
  for tz_res_name in tz_res_names:
    shutil.copy('%s/%s' % (res_src_dir, tz_res_name), res_staging_dir)

  # Create a .lst file to pass to pkgdata.
  tz_files_file = '%s/tzdata.lst' % res_staging_dir
  with open(tz_files_file, "a") as tz_files:
    for tz_res_name in tz_res_names:
      tz_files.write('%s\n' % tz_res_name)

  icu_lib_dir = '%s/lib' % icu_build_dir
  pkg_data_bin = '%s/bin/pkgdata' % icu_build_dir

  # Run pkgdata to create a .dat file.
  icu_env = os.environ.copy()
  icu_env["LD_LIBRARY_PATH"] = icu_lib_dir

  # pkgdata treats the .lst file it is given as relative to CWD, and the path also affects the
  # resource names in the .dat file produced so we change the CWD.
  os.chdir(res_staging_dir)

  # -F : force rebuilding all data
  # -m common : create a .dat
  # -v : verbose
  # -T . : use "." as a temp dir
  # -d . : use "." as the dest dir
  # -p <name> : Set the "data name"
  p = subprocess.Popen(
      [pkg_data_bin, '-F', '-m', 'common', '-v', '-T', '.', '-d', '.', '-p',
          icu_package, tz_files_file],
      env=icu_env)
  p.wait()
  if p.returncode != 0:
    print('pkgdata failed with status code: %s' % p.returncode)

  # Copy the .dat to the chosen place / name.
  generated_dat_file = '%s/%s' % (res_staging_dir, icu_package_dat)
  shutil.copyfile(generated_dat_file, dest_file)
  print('ICU overlay .dat can be found here: %s' % dest_file)

  # Switch back to the original working cwd.
  os.chdir(original_working_dir)

def _MakeLangInfo():
  """ Regenerates icu4c/source/data/misc/langInfo.txt.
  Returns true if the file was changed and false otherwise.

  This is implementation detail, should not be called outside
  of this script.
  """

  # Generate icu4c/source/data/misc/langInfo.txt by a ICU4J tool
  langInfo_dst_path = os.path.join(icu4cDir(), 'data/misc/langInfo.txt')
  print('Building %s' % langInfo_dst_path)
  langInfo_out_path = '/tmp/langInfo.txt'  # path hardcoded in the LocaleDistanceBuilder tool
  if os.path.exists(langInfo_out_path):
    os.remove(langInfo_out_path)

  icu4j_dir = icu4jDir()
  os.chdir(icu4j_dir)
  subprocess.check_call(['ant', 'icu4jJar'])
  os.chdir(os.path.join(icu4j_dir, 'tools', 'misc'))
  subprocess.check_call(['ant', 'jar'])
  subprocess.check_call([
    'java',
    '-cp',
    'out/lib/icu4j-tools.jar:../../icu4j.jar',
    'com.ibm.icu.dev.tool.locale.LocaleDistanceBuilder',
  ])
  if (filecmp.cmp(langInfo_dst_path, langInfo_out_path)):
    print('The files {src} and {dst} are the same'.format(src=langInfo_out_path, dst=langInfo_dst_path))
    return False

  print('Copying {src} to {dst}'.format(src=langInfo_out_path, dst=langInfo_dst_path))
  shutil.copyfile(langInfo_out_path, langInfo_dst_path)
  return True

def GenerateIcuDataFiles():
  """ There are ICU files generation of which depends on ICU itself.
  This method repeatedly builds ICU and re-generates these files until they
  converge, i.e. subsequent builds do not change these files.
  """
  last_icu_build_dir = _MakeIcuDataFilesOnce()

  # If icu4c/source/data/misc/langInfo.txt is re-generated, the binary data files need to be
  # re-generated. MakeIcuDataFiles() is called until it converges because the re-generation
  # depends icu4j, and icu4j depends on the binary data files.
  while _MakeLangInfo():
    last_icu_build_dir = _MakeIcuDataFilesOnce()

  _MakeIcuDataFilesWithoutTimeZoneFiles(last_icu_build_dir)

def _MakeIcuDataFilesOnce():
  """Builds ICU and copies .dat and .jar files to expected places.
  Build is invoked only once. It is unlikely that you need to call
  this method outside of this script.

  This is a low-level method.
  Please check :func:`GenerateIcuDataFiles()` for caveats.
  """
  i18nutil.SwitchToNewTemporaryDirectory()
  icu_build_dir = '%s/icu' % os.getcwd()

  PrepareIcuBuild(icu_build_dir, data_filters_json=ICU_MLDATA_FILTERS)

  MakeAndCopyIcuDataFiles(icu_build_dir)

  return icu_build_dir

def _MakeIcuDataFilesWithoutTimeZoneFiles(icu_build_dir):
  """
  Remove the timezone .res files from the .dat file in order to save ~200 KB file size.
  TODO (b/206956042): Move this to the first build whenhttps://unicode-org.atlassian.net/browse/ICU-21769 is fixed.
  Now another build is needed to build a new .dat file without the timezone files.
  """
  # A manual removal of the .lst file is needed to force GNUmake to rebuild the .lst file
  list_file_path = pathlib.Path(icu_build_dir, 'data/out/tmp/icudata.lst')
  list_file_path.unlink(missing_ok=True)

  PrepareIcuBuild(icu_build_dir, data_filters_json=ICU_DATA_FILTERS)
  # copy_icu4c_dat_file_only is set to true to avoid copying the ICU4J data or other files
  # because the data files may be incomplete to be consumed for a host tool.
  # The ICU4J implementation on device doesn't use the ICU4J data files,
  # e.g. ./icu4j/main/shared/data/icudata.jar
  MakeAndCopyIcuDataFiles(icu_build_dir, copy_icu4c_dat_file_only=True)

def CopyLicenseFiles(target_dir):
  """Copies ICU license files to the target_dir"""

  license_file = '%s/main/shared/licenses/LICENSE' % icu4jDir()
  print('Copying %s to %s ...' % (license_file, target_dir))
  shutil.copy(license_file, target_dir)

