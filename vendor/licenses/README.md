# Additional asset licenses

`OFL-1.1.txt` is the complete SIL Open Font License 1.1, copied from the
[SPDX license list, version 3.27.0](https://github.com/spdx/license-list-data/blob/v3.27.0/text/OFL-1.1.txt).

KaTeX's npm package includes mathematical fonts with OFL notices embedded in
their metadata, while its top-level `LICENSE` covers the MIT-licensed software.
The build reads the copyright and reserved font names from the original TTF
files and appends this full OFL text to the distributed
`THIRD_PARTY_NOTICES.txt`. The fonts are embedded without modification.

The build does not download licenses or other resources.
