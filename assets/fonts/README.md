# HELIX GUI Math Fonts

Place licensed Euclid font files here to make the HELIX GUI render variables
and mathematical symbols with the requested equation-style typeface.

Supported extensions:

```text
*.ttf
*.otf
*.ttc
```

Preferred examples:

```text
Euclid.ttf
EuclidSymbol.ttf
EuclidMath.ttf
```

At startup, `code/sclas_remote_gui.py` loads fonts from this folder with
`QFontDatabase.addApplicationFont`. If no Euclid font is present, the GUI falls
back to Windows' built-in `Cambria Math`.

