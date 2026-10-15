"""Small, streaming Excel metadata export using only the standard library."""

import re
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

COLUMNS = [
    ("Streaming Release Date", "streaming_release_date", 24),
    ("Product Release Date", "product_release_date", 24),
    ("Actress", "actresses", 45),
    ("Distribution Product ID", "distribution_product_id", 26),
    ("Manufacturer Product ID", "manufacturer_product_id", 26),
    ("Title", "title", 70),
    ("Runtime", "runtime", 16),
    ("Series", "series", 30),
    ("Maker", "maker", 30),
    ("Label", "label", 30),
    ("Source URL", "source_url", 65),
]
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]")


def cell(value, reference, style=0):
    text = INVALID_XML.sub("", str(value) if value is not None else "")
    if len(text) > 32767:
        raise ValueError("One metadata value exceeds Excel's 32,767-character cell limit")
    return (
        f'<c r="{reference}" t="inlineStr" s="{style}"><is>'
        f'<t xml:space="preserve">{escape(text)}</t></is></c>'
    )


def write_workbook(path, movies):
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<Types
 xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default
 Extension="rels"
 ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default
 Extension="xml"
 ContentType="application/xml"/>
<Override
 PartName="/xl/workbook.xml"
 ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override
 PartName="/xl/worksheets/sheet1.xml"
 ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override
 PartName="/xl/styles.xml"
 ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<Relationships
 xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship
 Id="rId1"
 Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
 Target="xl/workbook.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            f'''<workbook
 xmlns="{NS}"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets>
<sheet
 name="Metadata"
 sheetId="1"
 r:id="rId1"/>
</sheets>
</workbook>''',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<Relationships
 xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship
 Id="rId1"
 Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
 Target="worksheets/sheet1.xml"/>
<Relationship
 Id="rId2"
 Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
 Target="styles.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/styles.xml",
            f'''<styleSheet
 xmlns="{NS}">
<fonts
 count="2">
<font>
<sz
 val="11"/>
<name
 val="Calibri"/>
</font>
<font>
<b/>
<color
 rgb="FFFFFFFF"/>
<sz
 val="11"/>
<name
 val="Calibri"/>
</font>
</fonts>
<fills
 count="3">
<fill>
<patternFill
 patternType="none"/>
</fill>
<fill>
<patternFill
 patternType="gray125"/>
</fill>
<fill>
<patternFill
 patternType="solid">
<fgColor
 rgb="FFD32342"/>
<bgColor
 indexed="64"/>
</patternFill>
</fill>
</fills>
<borders
 count="1">
<border/>
</borders>
<cellStyleXfs
 count="1">
<xf/>
</cellStyleXfs>
<cellXfs
 count="2">
<xf
 numFmtId="49"
 fontId="0"
 fillId="0"
 borderId="0"
 xfId="0"
 applyNumberFormat="1">
<alignment
 vertical="top"/>
</xf>
<xf
 numFmtId="49"
 fontId="1"
 fillId="2"
 borderId="0"
 xfId="0"
 applyFill="1"
 applyFont="1"
 applyNumberFormat="1"/>
</cellXfs>
<cellStyles
 count="1">
<cellStyle
 name="Normal"
 xfId="0"
 builtinId="0"/>
</cellStyles>
</styleSheet>''',
        )
        with archive.open("xl/worksheets/sheet1.xml", "w") as sheet:

            def write(text):
                sheet.write(text.encode("utf-8"))

            write(
                f'<worksheet xmlns="{NS}"><sheetViews><sheetView workbookViewId="0">'
                '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                '</sheetView></sheetViews><sheetFormatPr defaultRowHeight="18"/><cols>'
            )
            for index, (_, _, width) in enumerate(COLUMNS, 1):
                write(f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>')
            write('</cols><sheetData><row r="1" ht="24" customHeight="1">')
            for index, (label, _, _) in enumerate(COLUMNS):
                write(cell(label, f"{chr(65 + index)}1", 1))
            write("</row>")
            last = 1
            for last, movie in enumerate(movies, 2):
                if last > 1048576:
                    raise ValueError("Too many movies for one Excel worksheet; narrow the filter")
                write(f'<row r="{last}">')
                for index, (_, key, _) in enumerate(COLUMNS):
                    value = (
                        "; ".join(link.actress.name for link in movie.cast)
                        if key == "actresses"
                        else getattr(movie, key)
                    )
                    write(cell(value, f"{chr(65 + index)}{last}"))
                write("</row>")
            write(f'</sheetData><autoFilter ref="A1:K{last}"/></worksheet>')
