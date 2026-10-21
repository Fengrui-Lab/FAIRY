# Offline WOFOST soybean data

`soybean.yaml` is copied verbatim from the immutable source recorded in
`provenance.json`. Its SHA-256 is checked before use. Upstream attribution and
European Union Public License (EUPL) metadata remain in the file; the upstream
metadata does not identify an EUPL version. Source:
https://github.com/ajwdewit/WOFOST_crop_parameters/tree/1ca91d7dbb5aaf6b41462162de03a8254812d3a5

These are published European soybean parameter sets, not calibrated coefficients
for FAIRY Chinese cultivar names or its simulated soil and climate. Runtime never
downloads crop parameters. The original YAML inheritance is resolved locally.

`weather/` contains the public NASA POWER daily weather inputs for Harbin
(45.7 N, 126.6 E), May–October 2017–2019. Each input has a companion provenance
file recording the API request, source units and SHA-256. These are simulation
inputs, not generated farm runs. NASA POWER: https://power.larc.nasa.gov/
The historical local `path` in provenance records is not a runtime dependency.
