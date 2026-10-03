import re
from pathlib import Path
from types import SimpleNamespace
import discord
from rustbot.i18n import COMMAND_ES, STRINGS, lang_for, normalize_lang, t

SRC = Path(__file__).parents[1] / 'rustbot'


def test_language_detection_defaults_to_english():
    assert lang_for(SimpleNamespace(locale=discord.Locale.spain_spanish)) == 'es'
    assert lang_for(SimpleNamespace(locale=discord.Locale.latin_american_spanish)) == 'es'
    assert lang_for(SimpleNamespace(locale=discord.Locale.american_english)) == 'en'
    assert lang_for(SimpleNamespace(locale=discord.Locale.brazil_portuguese)) == 'en'
    assert lang_for(SimpleNamespace()) == 'en' and normalize_lang(None) == 'en'


def test_every_key_used_in_code_exists_in_both_languages():
    used = set()
    for path in SRC.glob('*.py'):
        used |= set(re.findall(r"""\bt\(\s*\w+\s*,\s*'([a-z0-9_.]+)'""", path.read_text(encoding='utf-8')))
    # Keys ending in '.' are dynamic prefixes ('cat.' + category); test_dynamic_keys_resolve covers them.
    missing = sorted(k for k in used if k not in STRINGS and not k.endswith('.'))
    assert not missing, missing
    for key, (en, es) in STRINGS.items():
        assert en and es, key
        # Placeholders must match so .format never fails in one language only.
        assert set(re.findall(r'{(\w+)', en)) == set(re.findall(r'{(\w+)', es)), key


def test_dynamic_keys_resolve():
    for cat in ('doors', 'walls', 'floors', 'windows', 'deployables', 'vehicles'):
        assert t('es', 'cat.' + cat) != 'cat.' + cat
    for key in ('side.hard', 'side.soft', 'group.siege', 'group.fire', 'raid.warn.siege', 'raid.warn.fire',
                'who.privacy.public', 'who.privacy.private', 'who.privacy.friendsonly'):
        assert key in STRINGS


def test_command_descriptions_have_spanish():
    descriptions = set()
    for path in SRC.glob('*.py'):
        text = path.read_text(encoding='utf-8')
        descriptions |= {a or b for a, b in re.findall(r"""description=(?:'([^']+)'|"([^"]+)")""", text)}
        for block in re.findall(r'describe\((.*?)\)\n', text, re.S):
            descriptions |= {a or b for a, b in re.findall(r"""=\s*(?:'([^']+)'|"([^"]+)")""", block)}
    missing = sorted(d for d in descriptions if d not in COMMAND_ES)
    assert not missing, missing


def test_fallbacks():
    assert t('xx', 'common.back') == 'Back'
    assert t('es', 'no.such.key') == 'no.such.key'
