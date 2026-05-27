import re


NAME_RE = re.compile(r"^[A-Za-z][A-Za-z' -]*[A-Za-z]$")
REFERENCE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._:/#-]*$')
TEXT_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9\s.,;:!?/%+#&()\'"-]*$')
USERNAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_.-]{2,49}$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def clean_spaces(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def title_case_name(value):
    value = clean_spaces(value)
    return ' '.join(
        part[:1].upper() + part[1:].lower()
        for part in value.split(' ')
    )


def is_valid_person_name(value, min_parts=2, min_part_length=2, max_length=100):
    value = clean_spaces(value)
    if len(value) > max_length or not NAME_RE.fullmatch(value):
        return False

    parts = [part for part in re.split(r'[\s-]+', value) if part]
    if len(parts) < min_parts:
        return False
    if any(len(part.replace("'", '')) < min_part_length for part in parts):
        return False
    if len(set(part.casefold() for part in parts)) == 1:
        return False
    return True


def is_valid_label(value, min_length=2, max_length=100):
    value = clean_spaces(value)
    if len(value) < min_length or len(value) > max_length:
        return False
    return bool(TEXT_RE.fullmatch(value)) and any(char.isalpha() for char in value)


def is_valid_reference(value, max_length=120):
    value = clean_spaces(value)
    if not value or len(value) > max_length:
        return False
    return bool(REFERENCE_RE.fullmatch(value))


def is_valid_username(value):
    return bool(USERNAME_RE.fullmatch(clean_spaces(value)))


def is_valid_email(value):
    return bool(EMAIL_RE.fullmatch(clean_spaces(value).lower()))


def is_valid_phone_number(value):
    return bool(re.fullmatch(r'\+?\d{7,15}', clean_spaces(value)))


def is_valid_national_id(value):
    return bool(re.fullmatch(r'\d{5,20}', clean_spaces(value)))
