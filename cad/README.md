# CAD

Keep enclosure design files separate from generated print artifacts:

```text
enclosure/source/    Editable FreeCAD, OpenSCAD, STEP, or other source files
enclosure/exports/   Generated STL, 3MF, and manufacturing STEP files
enclosure/previews/  PNG or JPEG renders showing the current design
```

Generated exports are ignored by default because they can be reproduced from
the source model. Remove the relevant `.gitignore` entry if an export should be
versioned as a release artifact.

