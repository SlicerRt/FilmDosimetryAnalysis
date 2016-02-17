cmake_minimum_required(VERSION 2.8.9)

#-----------------------------------------------------------------------------
set(EXTENSION_NAME FilmDosimetryAnalysis)

# ------------------------------------------------------------------------
set(FILMDOSIMETRY_VERSION_MAJOR "0")
set(FILMDOSIMETRY_VERSION_MINOR "1")
set(FILMDOSIMETRY_VERSION_PATCH "0")
set(FILMDOSIMETRY_VERSION ${FILMDOSIMETRY_VERSION_MAJOR}.${FILMDOSIMETRY_VERSION_MINOR}.${FILMDOSIMETRY_VERSION_PATCH})

#-----------------------------------------------------------------------------
set(EXTENSION_HOMEPAGE "http://www.slicer.org/slicerWiki/index.php/Documentation/Nightly/Modules/FilmDosimetry")
set(EXTENSION_CATEGORY "Radiotherapy")
set(EXTENSION_CONTRIBUTORS "Kevin Alexander (KGH, Queen's University), Csaba Pinter (PerkLab, Queen's University)")
set(EXTENSION_DESCRIPTION "Slicelet covering the film dosimetry analysis workflow used in commissioning new radiation techniques and to validate the accuracy of radiation treatment by enabling visual comparison of the planned dose to the delivered dose, where correspondence between the two dose distributions is achieved using embedded landmarks. Gel dosimetry is based on imaging chemical systems spatially fixed in gelatin, which exhibit a detectable change upon irradiation.")
set(EXTENSION_ICONURL "http://www.slicer.org/slicerWiki/images/f/f1/FilmDosimetry_Logo_128x128.png")
set(EXTENSION_SCREENSHOTURLS "")
set(EXTENSION_DEPENDS "SlicerRT")

#-----------------------------------------------------------------------------
find_package(Slicer COMPONENTS ConfigurePrerequisites REQUIRED)
project(FilmDosimetryAnalysis)
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
add_subdirectory(FilmDosimetryAnalysis)

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_CPACK})
