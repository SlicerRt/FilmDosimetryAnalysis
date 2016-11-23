cmake_minimum_required(VERSION 2.8.9)

#-----------------------------------------------------------------------------
set(EXTENSION_NAME FilmDosimetryAnalysis)

# ------------------------------------------------------------------------
set(FILMDOSIMETRY_VERSION_MAJOR "1")
set(FILMDOSIMETRY_VERSION_MINOR "0")
set(FILMDOSIMETRY_VERSION_PATCH "0")
set(FILMDOSIMETRY_VERSION ${FILMDOSIMETRY_VERSION_MAJOR}.${FILMDOSIMETRY_VERSION_MINOR}.${FILMDOSIMETRY_VERSION_PATCH})

#-----------------------------------------------------------------------------
set(EXTENSION_HOMEPAGE "http://www.slicer.org/slicerWiki/index.php/Documentation/Nightly/Modules/FilmDosimetry")
set(EXTENSION_CATEGORY "Radiotherapy")
set(EXTENSION_CONTRIBUTORS "Csaba Pinter (PerkLab, Queen's University), Alec Robinson (PerkLab, Queen's University), Kevin Alexander (KGH, Queen's University)")
set(EXTENSION_DESCRIPTION "Film dosimetry analysis is a 2D dosimetry tool used in commissioning new radiation techniques and to validate the accuracy of radiation treatment by enabling visual comparison of the planned dose to the delivered dose")
set(EXTENSION_ICONURL "http://www.slicer.org/slicerWiki/images/1/16/FilmDosimetry_Logo_128x128.png")
set(EXTENSION_SCREENSHOTURLS "https://www.slicer.org/slicerWiki/images/8/8c/FilmDosimetry_1.0_Gamma.png https://www.slicer.org/slicerWiki/images/7/72/FilmDosimetry_1.0_Registration.png https://www.slicer.org/slicerWiki/images/4/4c/FilmDosimetry_1.0_CalibrationFunction.png https://www.slicer.org/slicerWiki/images/d/d8/FilmDosimetry_1.0_CalibrationBatch.png")
set(EXTENSION_DEPENDS "SlicerRT")

#-----------------------------------------------------------------------------
project(FilmDosimetryAnalysis)
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
add_subdirectory(FilmDosimetryAnalysis)

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_CPACK})
