"""Bounded, explicitly referenced document input for the proposal Builder."""
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree


def referenced_documents(order):
    text = '\n'.join([order.goal, order.context or '', *order.acceptance_criteria])
    paths = list(getattr(order, 'reference_paths', []))
    # Remove whole URL tokens before matching filesystem paths, including IPv6 hosts, query strings
    # and trailing-dot hostnames whose slashes otherwise look like standalone POSIX references.
    text = re.sub(r'''\b[A-Za-z][A-Za-z0-9+.-]*://[^\s<>"'`]+''', ' ', text)
    # A drive letter that starts a token (not the 'p' of 'http://', not a URL scheme '://') begins a document path.
    # A path never contains = * ? ' ( ): a sentence such as "E:\proj = a game ... see notes.md" is prose, not one path.
    paths += re.findall(r'(?<![A-Za-z0-9])[A-Za-z]:[/\\](?![/\\])[^\r\n"<>|`=*?\x27()]*?\.(?:docx|md|txt)(?=[\s"\x27`)\],;:]|$)', text, re.I)
    # POSIX references: only a standalone absolute path, never a URL's /path or a repo-relative docs/file.md.
    # Spaces are supported in quoted paths; unquoted paths end at whitespace to avoid consuming prose.
    quoted = r'''(["'`])(/(?!/)[^\r\n"'`<>|=*?]*?\.(?:docx|md|txt))\1'''
    paths += [match[1] for match in re.findall(quoted, text, re.I)]
    paths += re.findall(r'''(?<![A-Za-z0-9_:/\\"'`])/(?!/)[^\s"<>|`=*?'()]+?\.(?:docx|md|txt)(?=[\s"'`)\],;:]|$)''', text, re.I)
    documents = {}
    for value in dict.fromkeys(paths):
        path = Path(value)
        try:
            if not path.is_absolute() or path.is_symlink():
                raise ValueError('Reference must be an absolute regular file')
            if path.stat().st_size > 10_000_000:
                raise ValueError('Reference exceeds 10 MB')
            if path.suffix.lower() == '.docx':
                with zipfile.ZipFile(path) as archive:
                    info = archive.getinfo('word/document.xml')
                    if info.file_size > 5_000_000:
                        raise ValueError('Document XML exceeds limit')
                    root = ElementTree.fromstring(archive.read(info))
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                content = '\n'.join(''.join(p.itertext()) for p in root.findall('.//w:p', ns))
            elif path.suffix.lower() in {'.txt', '.md'}:
                content = path.read_text(encoding='utf-8')
            else:
                raise ValueError('Unsupported reference format')
            if len(content) > 100_000 or sum(len(v) for v in documents.values()) + len(content) > 200_000:
                raise ValueError('Reference text exceeds context budget')
            documents[str(path)] = content
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise ValueError(f'REFERENCE_INPUT_UNAVAILABLE: {value}: {exc}') from exc
    return documents
