"""Owner-confirmed fixture corrections to derived artwork, never original PDFs."""

def correct_floor2_cupboards(root):
    replacements = {
        'M9082 3206C8865.991 3206.7652 8690.292 3031.0657 8690 2814': None,
        'M9082 3671C8865.991 3671.3304 8690.292 3495.6309 8690 3278': None,
        'M8690 2814H9082V3242H9545V2778H9082': 'M9082 2778V3242H9545V2778Z',
        'M8690 3278H9082V3707H9545V3242H9082': 'M9082 3242V3707H9545V3242Z',
    }
    changed = 0
    for parent in root.iter():
        for child in list(parent):
            path = child.get('d')
            if path not in replacements:
                continue
            replacement = replacements[path]
            if replacement is None:
                parent.remove(child)
            else:
                child.set('d', replacement)
            changed += 1
    if changed not in (0,4) or not all(any(p.get('d') == value for p in root.iter()) for value in replacements.values() if value):
        raise ValueError('Floor 2 cupboard artwork changed; review the owner-confirmed fixture paths')
    return bool(changed)
