# P6SCGI ShowDoc Offline Mirror

This directory is generated from the public ShowDoc project `P6SCGI API（CN）`.

- Pages: 1012
- Source: http://p6scgi-api.p6sai.com:4999/web/#/663863654
- Generated files: one Markdown file per ShowDoc page.

Search examples:

```bash
rg "UpdatePersonInfoAndFaceImage" docs/p6scgi-showdoc
rg "FaceUUID" docs/p6scgi-showdoc
rg "QueryPersonInfoListCount" docs/p6scgi-showdoc
```

Regenerate:

```bash
python3 scripts/sync_p6scgi_showdoc.py --output docs/p6scgi-showdoc --delay 0.35
```
