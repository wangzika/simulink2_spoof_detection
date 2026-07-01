# GNSS Spoofing Literature PDFs

This folder stores the reproducible literature-download manifest used for the manuscript.

```bash
python3 tools/download_reference_papers.py
```

Downloaded PDFs are written to:

```text
paper/literature/papers/
```

The PDF files are intentionally ignored by git because they are large binary files and because some publishers require manual access even for open-access papers. The tracked files are:

```text
paper/literature/reference_papers.csv
paper/literature/reference_papers_downloaded.json
tools/download_reference_papers.py
```

Current local download status:

- 19 PDFs downloaded successfully.
- 4 open-access publisher links returned HTTP 403 to scripted downloads and should be downloaded manually in a browser if needed:
  - `spravil2023nmea`
  - `jafarnia2012review`
  - `androjna2020maritime`
  - `leite2021gnsssd`

The manuscript bibliography is maintained in:

```text
paper/references.bib
```
