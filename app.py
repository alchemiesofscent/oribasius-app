"""
Oribasius Collectiones Medicae - Scholarly Database
A web application for collaborative editing, analysis, and linking of ancient medical texts.

Enhanced with:
- Author/Sect management
- Ingredient tagging
- Raeder CMG edition references
- Lemmatized Greek search
- Custom URN scheme
"""

import os
import shutil
import tempfile
from flask import Flask, render_template, request, jsonify, send_file, redirect
from sqlalchemy.engine.url import make_url
import logging
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy import inspect, text
import csv
import io
import json
from datetime import datetime
from collections import Counter, defaultdict
import re
import unicodedata

# Shared color palette for author-based visualizations
AUTHOR_PALETTE = [
    '#e41a1c',  # Bright red
    '#377eb8',  # Strong blue
    '#4daf4a',  # Green
    '#984ea3',  # Purple
    '#ff7f00',  # Orange
    '#ffff33',  # Yellow
    '#a65628',  # Brown
    '#f781bf',  # Pink
    '#999999',  # Gray
    '#66c2a5',  # Teal
    '#fc8d62',  # Salmon
    '#8da0cb',  # Lavender
    '#e78ac3',  # Rose
    '#a6d854',  # Lime
    '#ffd92f',  # Gold
    '#e5c494',  # Tan
    '#b3b3b3',  # Light gray
    '#8dd3c7',  # Aqua
    '#bebada',  # Periwinkle
    '#fb8072',  # Coral
    '#80b1d3',  # Sky blue
    '#fdb462',  # Peach
    '#b3de69',  # Yellow-green
    '#fccde5',  # Light pink
    '#d9d9d9'   # Pale gray
]

SCHOOL_COLORS = {
    'Galen': '#e41a1c',
    'Pneumatist': '#377eb8',
    'Methodist': '#4daf4a',
    'Empiricist': '#984ea3',
    'Dogmatist': '#ff7f00',
    'Other': '#999999'
}

app = Flask(__name__)
# Configurable DB URL; default to bundled sqlite file copied to a writable path for deploys
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

def get_database_uri():
    env_uri = os.environ.get('DATABASE_URL')
    base_db = os.path.join(BASE_DIR, 'oribasius.db')

    def prepare_sqlite_uri(uri, fallback_path):
        try:
            url = make_url(uri)
        except Exception:
            return uri

        if not url.drivername.startswith('sqlite'):
            return uri

        target_path = url.database or fallback_path
        dir_path = os.path.dirname(target_path) or '.'

        # If target dir not writable (e.g., render read-only source), copy to /tmp
        if not os.access(dir_path, os.W_OK):
            tmp_path = os.path.join(tempfile.gettempdir(), 'oribasius.db')
            if os.path.exists(base_db):
                shutil.copy2(base_db, tmp_path)
            elif target_path and os.path.exists(target_path):
                shutil.copy2(target_path, tmp_path)
            url = url.set(database=tmp_path)
            return str(url)

        # If target path missing but base db exists, seed it
        if target_path and not os.path.exists(target_path) and os.path.exists(base_db):
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(base_db, target_path)

        return str(url)

    if env_uri:
        return prepare_sqlite_uri(env_uri, base_db)

    # Default: copy bundled db to /tmp for writable runtime
    tmp_db = os.path.join(tempfile.gettempdir(), 'oribasius.db')
    if os.path.exists(base_db):
        shutil.copy2(base_db, tmp_db)
        return f"sqlite:///{tmp_db}"
    return f"sqlite:///{base_db}"

app.config['SQLALCHEMY_DATABASE_URI'] = get_database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['DEMO_MODE'] = os.environ.get('DEMO_MODE', 'false').lower() == 'true'

CORS(app)
db = SQLAlchemy(app)

# Log resolved DB info for debugging deploy environments
def log_db_info(uri):
    try:
        url = make_url(uri)
    except Exception:
        logging.info("DB URI (raw): %s", uri)
        return
    logging.info("DB driver: %s", url.drivername)
    logging.info("DB database: %s", url.database)
    if url.drivername.startswith('sqlite') and url.database:
        logging.info("SQLite file exists: %s", os.path.exists(url.database))
        logging.info("SQLite dir writable: %s", os.access(os.path.dirname(url.database) or '.', os.W_OK))
        logging.info("SQLite path: %s", url.database)

# =============================================================================
# DATABASE MODELS
# =============================================================================

class SourceAuthor(db.Model):
    """Authors cited by Oribasius (Galen, Rufus, Antyllus, etc.)"""
    __tablename__ = 'source_authors'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    name_greek = db.Column(db.String(200))
    sect = db.Column(db.String(100))  # Pneumatist, Methodist, Empiricist, Rationalist, Dogmatist, Unknown
    sect_certain = db.Column(db.Boolean, default=True)
    floruit = db.Column(db.String(100))  # e.g., "2nd c. CE"
    tlg_id = db.Column(db.String(50))  # TLG author number if available
    notes = db.Column(db.Text)
    
    entries = db.relationship('Entry', back_populates='source_author_rel', lazy='dynamic')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'name_greek': self.name_greek,
            'sect': self.sect,
            'sect_certain': self.sect_certain,
            'floruit': self.floruit,
            'tlg_id': self.tlg_id,
            'notes': self.notes,
            'entry_count': self.entries.count()
        }

class Ingredient(db.Model):
    """Substances mentioned in recipes/preparations"""
    __tablename__ = 'ingredients'
    
    id = db.Column(db.Integer, primary_key=True)
    name_greek = db.Column(db.String(200), nullable=False)
    name_latin = db.Column(db.String(200))
    name_english = db.Column(db.String(200))
    category = db.Column(db.String(100))  # plant, animal, mineral, compound, other
    subcategory = db.Column(db.String(100))  # resin, root, seed, oil, etc.
    dioscorides_ref = db.Column(db.String(100))  # e.g., "1.24"
    modern_id = db.Column(db.String(200))  # Modern botanical/chemical name
    notes = db.Column(db.Text)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name_greek': self.name_greek,
            'name_latin': self.name_latin,
            'name_english': self.name_english,
            'category': self.category,
            'subcategory': self.subcategory,
            'dioscorides_ref': self.dioscorides_ref,
            'modern_id': self.modern_id,
            'notes': self.notes
        }

# Junction table for Entry-Ingredient many-to-many
entry_ingredients = db.Table('entry_ingredients',
    db.Column('entry_id', db.Integer, db.ForeignKey('entries.id'), primary_key=True),
    db.Column('ingredient_id', db.Integer, db.ForeignKey('ingredients.id'), primary_key=True),
    db.Column('quantity', db.String(200)),  # e.g., "δραχμαὶ δύο"
    db.Column('preparation', db.String(200))  # e.g., "κεκομμένον"
)

class Entry(db.Model):
    __tablename__ = 'entries'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Attribution
    author_named = db.Column(db.String(200))  # Name as given in text
    source_author_id = db.Column(db.Integer, db.ForeignKey('source_authors.id'))
    author = db.Column(db.String(200))  # Legacy field
    author_group = db.Column(db.String(100))  # Legacy field for grouping
    
    # Location in Oribasius
    book = db.Column(db.Integer)
    chapter = db.Column(db.Integer)
    section = db.Column(db.Integer)
    chapter_title = db.Column(db.String(100))
    
    # Raeder CMG edition reference
    raeder_volume = db.Column(db.String(20))  # e.g., "VI.1.1"
    raeder_page = db.Column(db.Integer)
    raeder_line_start = db.Column(db.Integer)
    raeder_line_end = db.Column(db.Integer)
    
    # Text content
    title_greek = db.Column(db.Text)
    body_greek = db.Column(db.Text)
    translation_title = db.Column(db.Text)
    translation_content = db.Column(db.Text)
    
    # Lemmatized index (JSON: {"lemma": [positions]})
    lemma_index = db.Column(db.Text)
    
    # Legacy location field
    location = db.Column(db.String(200))
    
    # Metrics
    word_count = db.Column(db.Integer)
    
    # Notes
    note1 = db.Column(db.Text)
    note2 = db.Column(db.Text)
    note3 = db.Column(db.Text)
    note4 = db.Column(db.Text)
    
    # Classification (legacy)
    pneumatist = db.Column(db.String(100))
    
    # Themes (JSON array)
    themes = db.Column(db.Text)
    
    # URNs
    urn_cts = db.Column(db.String(300))  # CTS URN: urn:cts:greekMed:oribasius.coll:1.2.3
    urn_raeder = db.Column(db.String(300))  # Raeder ref: urn:cite:alchemies:raeder:VI.1.1.23.1-5
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    ingredients = db.relationship('Ingredient', secondary=entry_ingredients, 
                                   backref=db.backref('entries', lazy='dynamic'))
    source_author_rel = db.relationship('SourceAuthor', back_populates='entries', lazy='joined')
    
    def to_dict(self, include_ingredients=False):
        result = {
            'id': self.id,
            'author_named': self.author_named,
            'source_author_id': self.source_author_id,
            'source_author': self.source_author_rel.to_dict() if self.source_author_rel else None,
            'author': self.author,
            'author_group': self.author_group,
            'book': self.book,
            'chapter': self.chapter,
            'section': self.section,
            'chapter_title': self.chapter_title,
            'raeder_volume': self.raeder_volume,
            'raeder_page': self.raeder_page,
            'raeder_line_start': self.raeder_line_start,
            'raeder_line_end': self.raeder_line_end,
            'title_greek': self.title_greek,
            'body_greek': self.body_greek,
            'translation_title': self.translation_title,
            'translation_content': self.translation_content,
            'location': self.location,
            'word_count': self.word_count,
            'note1': self.note1,
            'note2': self.note2,
            'note3': self.note3,
            'note4': self.note4,
            'pneumatist': self.pneumatist,
            'themes': json.loads(self.themes) if self.themes else [],
            'urn_cts': self.urn_cts,
            'urn_raeder': self.urn_raeder,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        if include_ingredients:
            result['ingredients'] = [i.to_dict() for i in self.ingredients]
        return result
    
    def generate_urns(self):
        """Generate both URN schemes for this entry"""
        # CTS URN using standard TLG numbers
        # tlg0722 = Oribasius
        # tlg001 = Collectiones Medicae
        parts = []
        if self.book:
            parts.append(str(self.book))
        if self.chapter:
            parts.append(str(self.chapter))
        if self.section:
            parts.append(str(self.section))
        
        if parts:
            self.urn_cts = f"urn:cts:greekLit:tlg0722.tlg001:{'.'.join(parts)}"
        
        # Raeder CMG edition reference
        if self.raeder_volume and self.raeder_page:
            raeder_ref = f"{self.raeder_volume}.{self.raeder_page}"
            if self.raeder_line_start:
                raeder_ref += f".{self.raeder_line_start}"
                if self.raeder_line_end and self.raeder_line_end != self.raeder_line_start:
                    raeder_ref += f"-{self.raeder_line_end}"
            self.urn_raeder = f"urn:cite:alchemies:raeder:{raeder_ref}"

class EditHistory(db.Model):
    __tablename__ = 'edit_history'
    
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey('entries.id'))
    field_changed = db.Column(db.String(100))
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    editor_name = db.Column(db.String(200))
    edited_at = db.Column(db.DateTime, default=datetime.utcnow)

class Theme(db.Model):
    __tablename__ = 'themes'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True)
    description = db.Column(db.Text)
    color = db.Column(db.String(7))  # hex color

class ThematicDivision(db.Model):
    """
    Hierarchical structure of Oribasius's organizational scheme.
    Captures the Four-Fold Division and its subdivisions.
    """
    __tablename__ = 'thematic_divisions'

    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(20))  # 'part', 'division', 'subdivision', 'section'
    parent_id = db.Column(db.Integer, db.ForeignKey('thematic_divisions.id'))
    children = db.relationship('ThematicDivision', backref=db.backref('parent', remote_side=[id]))
    numeral = db.Column(db.String(20))
    code = db.Column(db.String(50), unique=True)
    title_latin = db.Column(db.String(300))
    title_english = db.Column(db.String(300))
    definition = db.Column(db.Text)
    books_start = db.Column(db.Integer)
    books_end = db.Column(db.Integer)
    chapter_start = db.Column(db.Integer)  # For fine-grained section mapping
    chapter_end = db.Column(db.Integer)
    color = db.Column(db.String(7))
    sort_order = db.Column(db.Integer)

    def to_dict(self, include_children=False):
        result = {
            'id': self.id,
            'level': self.level,
            'parent_id': self.parent_id,
            'numeral': self.numeral,
            'code': self.code,
            'title_latin': self.title_latin,
            'title_english': self.title_english,
            'definition': self.definition,
            'books_start': self.books_start,
            'books_end': self.books_end,
            'color': self.color,
            'sort_order': self.sort_order
        }
        if include_children:
            result['children'] = [c.to_dict(include_children=True) for c in sorted(self.children, key=lambda x: x.sort_order or 0)]
        return result

# =============================================================================
# GREEK LEMMATIZATION UTILITIES
# =============================================================================

def normalize_greek(text):
    """
    Normalize Greek text for comparison:
    - Remove diacritics (accents, breathings)
    - Lowercase
    - Normalize Unicode
    """
    if not text:
        return ""
    # Normalize to NFD (decomposed form)
    text = unicodedata.normalize('NFD', text)
    # Remove combining diacritical marks (accents, breathings, etc.)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    # Normalize back and lowercase
    return unicodedata.normalize('NFC', text).lower()

def extract_greek_words(text):
    """Extract Greek words from text"""
    if not text:
        return []
    # Match Greek Unicode ranges
    pattern = r'[\u0370-\u03FF\u1F00-\u1FFF]+'
    return re.findall(pattern, text)

# Simple Greek lemmatization rules (expandable)
# Maps normalized endings to possible lemma endings
GREEK_LEMMA_RULES = [
    # Nouns - genitive to nominative
    (r'ου$', 'ος'),  # 2nd decl masc
    (r'ης$', 'η'),   # 1st decl fem
    (r'ας$', 'α'),   # 1st decl fem
    (r'ων$', 'ος'),  # 2nd decl gen pl -> nom sg (rough)
    # Verbs - common inflections to infinitive/1st person
    (r'ει$', 'ειν'),
    (r'ουσι$', 'ειν'),
    (r'εται$', 'εσθαι'),
    (r'ονται$', 'εσθαι'),
    # Participles
    (r'ων$', 'ων'),
    (r'ουσα$', 'ων'),
    (r'ον$', 'ων'),
    # Adjectives
    (r'ου$', 'ος'),
    (r'ῳ$', 'ος'),
    (r'ον$', 'ος'),
]

GREEK_STOPWORDS = {
    'ο','η','το','οι','αι','τα','του','των','τη','της','τασ','τοις','τασ','τους','τας','τον','την','τω','τῳ','τῳ','τῃ','και','δε','γαρ','μεν','δε','εν','εις','εκ','εξ','ως','ησαν','ην','εστι','εστιν','ου','ουκ','μη','ουδε','ουτε','μητε','αλλα','αλλ'
}

def simple_lemmatize(word):
    """
    Simple rule-based Greek lemmatization.
    Returns a list of possible lemma forms.
    For production, integrate CLTK or Morpheus.
    """
    normalized = normalize_greek(word)
    lemmas = {normalized}  # Always include normalized form
    
    for pattern, replacement in GREEK_LEMMA_RULES:
        if re.search(pattern, normalized):
            lemma = re.sub(pattern, replacement, normalized)
            lemmas.add(lemma)
    
    return list(lemmas)

def build_lemma_index(text):
    """
    Build a lemma index for Greek text.
    Returns JSON: {"lemma": [word_positions]}
    """
    words = extract_greek_words(text)
    index = defaultdict(list)
    
    for pos, word in enumerate(words):
        for lemma in simple_lemmatize(word):
            index[lemma].append(pos)
    
    return json.dumps(index, ensure_ascii=False)

def search_with_lemma(query, entries):
    """
    Search entries using lemmatized matching.
    Returns entries where any lemma form of query appears.
    """
    query_lemmas = set()
    for word in extract_greek_words(query):
        query_lemmas.update(simple_lemmatize(word))
    
    results = []
    for entry in entries:
        if not entry.lemma_index:
            continue
        try:
            index = json.loads(entry.lemma_index)
            for lemma in query_lemmas:
                if lemma in index:
                    results.append(entry)
                    break
        except json.JSONDecodeError:
            continue
    
    return results

# Routes
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/debug-db')
def debug_db():
    """Diagnostic endpoint for database location and connectivity"""
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    info = {
        "sqlalchemy_uri": uri,
        "driver": None,
        "database_path": None,
        "database_exists": None,
        "database_size_bytes": None,
        "database_writable": None,
        "bundled_db_exists": None,
        "bundled_db_size_bytes": None,
        "tmp_dir": tempfile.gettempdir(),
        "connection_test": "pending"
    }

    try:
        url = make_url(uri)
        info["driver"] = url.drivername
        if url.drivername.startswith('sqlite'):
            db_path = url.database or ''
            info["database_path"] = db_path
            info["database_exists"] = os.path.exists(db_path)
            info["database_size_bytes"] = os.path.getsize(db_path) if os.path.exists(db_path) else 0
            info["database_writable"] = os.access(db_path, os.W_OK) if os.path.exists(db_path) else False
        else:
            info["database_path"] = url.database
    except Exception as exc:
        info["driver"] = f"parse_error: {exc}"
        info["database_path"] = "unknown"

    bundled_db = os.path.join(BASE_DIR, 'oribasius.db')
    info["bundled_db_exists"] = os.path.exists(bundled_db)
    info["bundled_db_size_bytes"] = os.path.getsize(bundled_db) if os.path.exists(bundled_db) else 0

    try:
        count = Entry.query.count()
        info["connection_test"] = f"success: {count} entries"
    except Exception as exc:
        info["connection_test"] = f"failed: {exc}"

    return jsonify(info)

# =============================================================================
# URN RESOLVER
# =============================================================================

@app.route('/urn/<path:urn>')
def resolve_urn(urn):
    """Resolve a URN to an entry"""
    full_urn = f"urn:{urn}"
    entry = Entry.query.filter(
        db.or_(Entry.urn_cts == full_urn, Entry.urn_raeder == full_urn)
    ).first()
    if entry:
        return redirect(f'/#entry-{entry.id}')
    return jsonify({'error': 'URN not found'}), 404

# =============================================================================
# SOURCE AUTHORS API
# =============================================================================

@app.route('/api/authors', methods=['GET'])
def get_authors():
    authors = SourceAuthor.query.order_by(SourceAuthor.name).all()
    return jsonify([a.to_dict() for a in authors])

@app.route('/api/authors/<int:author_id>', methods=['GET'])
def get_author(author_id):
    author = SourceAuthor.query.get_or_404(author_id)
    return jsonify(author.to_dict())

@app.route('/api/authors', methods=['POST'])
def create_author():
    data = request.json
    author = SourceAuthor(
        name=data['name'],
        name_greek=data.get('name_greek'),
        sect=data.get('sect'),
        sect_certain=data.get('sect_certain', True),
        floruit=data.get('floruit'),
        tlg_id=data.get('tlg_id'),
        notes=data.get('notes')
    )
    db.session.add(author)
    db.session.commit()
    return jsonify(author.to_dict()), 201

@app.route('/api/authors/<int:author_id>', methods=['PUT'])
def update_author(author_id):
    author = SourceAuthor.query.get_or_404(author_id)
    data = request.json
    
    for field in ['name', 'name_greek', 'sect', 'sect_certain', 'floruit', 'tlg_id', 'notes']:
        if field in data:
            setattr(author, field, data[field])
    
    db.session.commit()
    return jsonify(author.to_dict())

@app.route('/api/authors/<int:author_id>', methods=['DELETE'])
def delete_author(author_id):
    author = SourceAuthor.query.get_or_404(author_id)
    db.session.delete(author)
    db.session.commit()
    return '', 204

# =============================================================================
# INGREDIENTS API
# =============================================================================

@app.route('/api/ingredients', methods=['GET'])
def get_ingredients():
    query = Ingredient.query
    
    if request.args.get('category'):
        query = query.filter(Ingredient.category == request.args.get('category'))
    if request.args.get('search'):
        search = f"%{request.args.get('search')}%"
        query = query.filter(
            db.or_(
                Ingredient.name_greek.ilike(search),
                Ingredient.name_latin.ilike(search),
                Ingredient.name_english.ilike(search)
            )
        )
    
    ingredients = query.order_by(Ingredient.name_greek).all()
    return jsonify([i.to_dict() for i in ingredients])

@app.route('/api/ingredients/<int:ingredient_id>', methods=['GET'])
def get_ingredient(ingredient_id):
    ingredient = Ingredient.query.get_or_404(ingredient_id)
    result = ingredient.to_dict()
    result['entries'] = [{'id': e.id, 'location': f"{e.book}.{e.chapter}"} for e in ingredient.entries]
    return jsonify(result)

@app.route('/api/ingredients', methods=['POST'])
def create_ingredient():
    data = request.json
    ingredient = Ingredient(
        name_greek=data['name_greek'],
        name_latin=data.get('name_latin'),
        name_english=data.get('name_english'),
        category=data.get('category'),
        subcategory=data.get('subcategory'),
        dioscorides_ref=data.get('dioscorides_ref'),
        modern_id=data.get('modern_id'),
        notes=data.get('notes')
    )
    db.session.add(ingredient)
    db.session.commit()
    return jsonify(ingredient.to_dict()), 201

@app.route('/api/ingredients/<int:ingredient_id>', methods=['PUT'])
def update_ingredient(ingredient_id):
    ingredient = Ingredient.query.get_or_404(ingredient_id)
    data = request.json
    
    for field in ['name_greek', 'name_latin', 'name_english', 'category', 
                  'subcategory', 'dioscorides_ref', 'modern_id', 'notes']:
        if field in data:
            setattr(ingredient, field, data[field])
    
    db.session.commit()
    return jsonify(ingredient.to_dict())

@app.route('/api/ingredients/<int:ingredient_id>', methods=['DELETE'])
def delete_ingredient(ingredient_id):
    ingredient = Ingredient.query.get_or_404(ingredient_id)
    db.session.delete(ingredient)
    db.session.commit()
    return '', 204

# =============================================================================
# ENTRIES API
# =============================================================================

@app.route('/api/entries', methods=['GET'])
def get_entries():
    query = Entry.query
    
    # Filtering
    if request.args.get('author'):
        query = query.filter(Entry.author == request.args.get('author'))
    if request.args.get('source_author_id'):
        query = query.filter(Entry.source_author_id == int(request.args.get('source_author_id')))
    if request.args.get('author_group'):
        query = query.filter(Entry.author_group == request.args.get('author_group'))
    if request.args.get('book'):
        query = query.filter(Entry.book == int(request.args.get('book')))
    if request.args.get('sect'):
        # Filter by author's sect
        query = query.join(SourceAuthor).filter(SourceAuthor.sect == request.args.get('sect'))
    if request.args.get('pneumatist'):
        query = query.filter(Entry.pneumatist == request.args.get('pneumatist'))
    if request.args.get('ingredient_id'):
        query = query.filter(Entry.ingredients.any(Ingredient.id == int(request.args.get('ingredient_id'))))
    
    # Text search
    search = request.args.get('search')
    lemma_search = request.args.get('lemma_search', 'false').lower() == 'true'
    
    if search:
        if lemma_search and any(ord(c) >= 0x0370 for c in search):
            # Lemmatized Greek search
            all_entries = query.all()
            entries = search_with_lemma(search, all_entries)
        else:
            # Standard text search
            search_pattern = f"%{search}%"
            query = query.filter(
                db.or_(
                    Entry.body_greek.ilike(search_pattern),
                    Entry.translation_content.ilike(search_pattern),
                    Entry.title_greek.ilike(search_pattern),
                    Entry.translation_title.ilike(search_pattern)
                )
            )
            entries = None
    else:
        entries = None
    
    # Sorting
    sort_by = request.args.get('sort_by', 'book')
    sort_order = request.args.get('sort_order', 'asc')
    
    if entries is None:
        if hasattr(Entry, sort_by):
            column = getattr(Entry, sort_by)
            if sort_order == 'desc':
                query = query.order_by(column.desc())
            else:
                query = query.order_by(column.asc())
        entries = query.all()
    
    include_ingredients = request.args.get('include_ingredients', 'false').lower() == 'true'
    return jsonify([e.to_dict(include_ingredients=include_ingredients) for e in entries])

@app.route('/api/entries/<int:entry_id>', methods=['GET'])
def get_entry(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    return jsonify(entry.to_dict(include_ingredients=True))

@app.route('/api/entries/<int:entry_id>', methods=['PUT'])
def update_entry(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    data = request.json
    editor_name = data.pop('editor_name', 'Anonymous')
    
    for field, value in data.items():
        if hasattr(entry, field):
            old_value = getattr(entry, field)
            if field == 'themes':
                value = json.dumps(value) if isinstance(value, list) else value
            setattr(entry, field, value)
            
            # Log the change
            if str(old_value) != str(value):
                history = EditHistory(
                    entry_id=entry_id,
                    field_changed=field,
                    old_value=str(old_value),
                    new_value=str(value),
                    editor_name=editor_name
                )
                db.session.add(history)
    
    # Recalculate word count and lemma index if Greek text changed
    if 'body_greek' in data:
        entry.word_count = len(re.findall(r'\S+', entry.body_greek or ''))
        entry.lemma_index = build_lemma_index(entry.body_greek)
    
    # Regenerate URNs if location fields changed
    if any(f in data for f in ['book', 'chapter', 'section', 'raeder_volume', 
                                'raeder_page', 'raeder_line_start', 'raeder_line_end']):
        entry.generate_urns()
    
    db.session.commit()
    return jsonify(entry.to_dict())

@app.route('/api/entries', methods=['POST'])
def create_entry():
    data = request.json
    if 'themes' in data and isinstance(data['themes'], list):
        data['themes'] = json.dumps(data['themes'])
    
    # Handle ingredients separately
    ingredient_ids = data.pop('ingredient_ids', [])
    
    entry = Entry(**data)
    
    # Set word count and lemma index
    if entry.body_greek:
        entry.word_count = len(re.findall(r'\S+', entry.body_greek))
        entry.lemma_index = build_lemma_index(entry.body_greek)
    
    # Generate URNs
    entry.generate_urns()
    
    # Add ingredients
    if ingredient_ids:
        ingredients = Ingredient.query.filter(Ingredient.id.in_(ingredient_ids)).all()
        entry.ingredients = ingredients
    
    db.session.add(entry)
    db.session.commit()
    return jsonify(entry.to_dict()), 201

@app.route('/api/entries/<int:entry_id>', methods=['DELETE'])
def delete_entry(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    return '', 204

@app.route('/api/entries/<int:entry_id>/ingredients', methods=['POST'])
def add_entry_ingredient(entry_id):
    """Add an ingredient to an entry"""
    entry = Entry.query.get_or_404(entry_id)
    data = request.json
    ingredient = Ingredient.query.get_or_404(data['ingredient_id'])
    
    if ingredient not in entry.ingredients:
        entry.ingredients.append(ingredient)
        db.session.commit()
    
    return jsonify(entry.to_dict(include_ingredients=True))

@app.route('/api/entries/<int:entry_id>/ingredients/<int:ingredient_id>', methods=['DELETE'])
def remove_entry_ingredient(entry_id, ingredient_id):
    """Remove an ingredient from an entry"""
    entry = Entry.query.get_or_404(entry_id)
    ingredient = Ingredient.query.get_or_404(ingredient_id)
    
    if ingredient in entry.ingredients:
        entry.ingredients.remove(ingredient)
        db.session.commit()
    
    return jsonify(entry.to_dict(include_ingredients=True))

@app.route('/api/filters', methods=['GET'])
def get_filter_options():
    """Get distinct values for filter dropdowns"""
    authors = db.session.query(Entry.author).distinct().all()
    author_groups = db.session.query(Entry.author_group).distinct().all()
    books = db.session.query(Entry.book).distinct().order_by(Entry.book).all()
    pneumatists = db.session.query(Entry.pneumatist).distinct().all()
    sects = db.session.query(SourceAuthor.sect).distinct().all()
    source_authors = SourceAuthor.query.order_by(SourceAuthor.name).all()
    ingredient_categories = db.session.query(Ingredient.category).distinct().all()
    
    raw_pneumatists = [p[0] for p in pneumatists]
    pneumatist_values = sorted({p for p in raw_pneumatists if p})
    if any(not p for p in raw_pneumatists):
        pneumatist_values = ['Unknown'] + pneumatist_values

    raw_sects = [s[0] for s in sects]
    sect_values = sorted({s for s in raw_sects if s})
    if any(not s for s in raw_sects):
        sect_values = ['Unknown'] + sect_values
    
    return jsonify({
        'authors': [a[0] for a in authors if a[0]],
        'author_groups': [a[0] for a in author_groups if a[0]],
        'books': [b[0] for b in books if b[0]],
        'pneumatists': pneumatist_values,
        'sects': sect_values,
        'source_authors': [{'id': a.id, 'name': a.name, 'sect': a.sect} for a in source_authors],
        'ingredient_categories': [c[0] for c in ingredient_categories if c[0]]
    })

@app.route('/api/analytics', methods=['GET'])
def get_analytics():
    """Comprehensive analytics for the corpus"""
    entries = Entry.query.all()
    
    # Word counts by author
    words_by_author = {}
    for e in entries:
        author = e.author or 'Unknown'
        words_by_author[author] = words_by_author.get(author, 0) + (e.word_count or 0)
    
    # Word counts by author group
    words_by_group = {}
    for e in entries:
        group = e.author_group or 'Unknown'
        words_by_group[group] = words_by_group.get(group, 0) + (e.word_count or 0)
    
    # Word counts by book
    words_by_book = {}
    entries_by_book = {}
    for e in entries:
        book = f"Book {e.book}" if e.book else 'Unknown'
        words_by_book[book] = words_by_book.get(book, 0) + (e.word_count or 0)
        entries_by_book[book] = entries_by_book.get(book, 0) + 1
    
    # Word counts by medical sect (via SourceAuthor)
    words_by_sect = {}
    for e in entries:
        if e.source_author_rel:
            sect = e.source_author_rel.sect or 'Unknown'
            certainty = '?' if not e.source_author_rel.sect_certain else ''
            sect_label = f"{sect}{certainty}"
        else:
            sect_label = 'Unclassified'
        words_by_sect[sect_label] = words_by_sect.get(sect_label, 0) + (e.word_count or 0)
    
    # Legacy pneumatist distribution (for backward compatibility)
    words_by_pneumatist = {}
    for e in entries:
        p = e.pneumatist or 'Unclassified'
        words_by_pneumatist[p] = words_by_pneumatist.get(p, 0) + (e.word_count or 0)
    
    # Ingredient statistics
    ingredient_counts = {}
    for e in entries:
        for ing in e.ingredients:
            key = ing.name_greek or ing.name_english
            ingredient_counts[key] = ingredient_counts.get(key, 0) + 1
    top_ingredients = sorted(ingredient_counts.items(), key=lambda x: -x[1])[:20]
    
    # Ingredient categories
    category_counts = defaultdict(int)
    for ing in Ingredient.query.all():
        cat = ing.category or 'Unknown'
        category_counts[cat] += len(list(ing.entries))
    
    # Total stats
    total_words = sum(e.word_count or 0 for e in entries)
    total_entries = len(entries)
    
    # Greek vocabulary frequency (lemmatized, stopwords removed)
    all_greek = ' '.join(e.body_greek or '' for e in entries)
    greek_words = re.findall(r'[\u0370-\u03FF\u1F00-\u1FFF]+', all_greek)
    lemma_counts = Counter()
    for w in greek_words:
        lemmas = simple_lemmatize(w)
        if not lemmas:
            continue
        normalized = sorted(normalize_greek(l) for l in lemmas)
        base = normalized[0]
        if base in GREEK_STOPWORDS:
            continue
        lemma_counts[base] += 1
    word_freq = lemma_counts.most_common(100)
    
    return jsonify({
        'total_words': total_words,
        'total_entries': total_entries,
        'total_authors': SourceAuthor.query.count(),
        'total_ingredients': Ingredient.query.count(),
        'words_by_author': words_by_author,
        'words_by_group': words_by_group,
        'words_by_book': words_by_book,
        'entries_by_book': entries_by_book,
        'words_by_sect': words_by_sect,
        'words_by_pneumatist': words_by_pneumatist,
        'top_ingredients': top_ingredients,
        'ingredient_categories': dict(category_counts),
        'top_greek_words': word_freq
    })


@app.route('/api/book-map', methods=['GET'])
def get_book_map():
    """Return chapter-level distribution by source author for visualization"""
    entries = Entry.query.all()
    books = defaultdict(lambda: defaultdict(lambda: {
        'entries': 0,
        'word_count': 0,
        'author_counts': defaultdict(int),
        'title': None,
        'translation_title': None
    }))
    authors_set = set()

    for e in entries:
        book_key = e.book if e.book is not None else 'Unknown'
        chap_key = e.chapter if e.chapter is not None else 'Unknown'
        bucket = books[book_key][chap_key]
        bucket['entries'] += 1
        bucket['word_count'] += e.word_count or 0
        if not bucket['title']:
            bucket['title'] = e.chapter_title or e.title_greek
        if not bucket['translation_title'] and e.translation_title:
            bucket['translation_title'] = e.translation_title
        author_name = e.source_author_rel.name if e.source_author_rel else (e.author or 'Unknown')
        authors_set.add(author_name)
        bucket['author_counts'][author_name] += (e.word_count or 0) or 1

    author_colors = build_author_colors(authors_set)

    books_list = []
    for book_key, chapters in books.items():
        chapter_items = []
        for chap_key, data in chapters.items():
            if data['author_counts']:
                top_author = max(data['author_counts'].items(), key=lambda x: x[1])[0]
            else:
                top_author = 'Unknown'
            chapter_items.append({
                'chapter': chap_key,
                'title': data['title'],
                'translation_title': data['translation_title'],
                'entries': data['entries'],
                'word_count': data['word_count'],
                'source_author': top_author,
                'color': author_colors.get(top_author, '#999999')
            })
        # sort numeric chapters first
        chapter_items.sort(key=lambda c: (9999 if c['chapter']=='Unknown' else int(c['chapter']), str(c['chapter'])))
        books_list.append({
            'book': book_key,
            'chapters': chapter_items
        })

    books_list.sort(key=lambda b: (9999 if b['book']=='Unknown' else int(b['book']), str(b['book'])))

    return jsonify({
        'books': books_list,
        'colors': author_colors
    })


@app.route('/api/book-map-v2', methods=['GET'])
def get_book_map_v2():
    """
    Book map with flexible grouping modes:
    - mode=author: individual authors (>threshold for named, rest as 'Other')
    - mode=school: Galen, Pneumatist, Methodist, Empiricist, Other
    """
    mode = request.args.get('mode', 'school')
    threshold = float(request.args.get('threshold', 0.05))

    entries = Entry.query.all()
    total_words = sum(e.word_count or 0 for e in entries)

    author_words = defaultdict(int)
    for e in entries:
        wc = e.word_count or 0
        author_name = e.source_author_rel.name if e.source_author_rel else (e.author or 'Unknown')
        author_words[author_name] += wc
    authors_set = set(author_words.keys())

    major_authors = {a for a, w in author_words.items() if total_words > 0 and w / total_words >= threshold}

    def get_school_group(entry):
        if entry.source_author_rel:
            name = entry.source_author_rel.name
            if name and 'Galen' in name:
                return 'Galen'
            sect = entry.source_author_rel.sect
            if sect in ('Pneumatist', 'Methodist', 'Empiricist', 'Dogmatist'):
                return sect
        return 'Other'

    def get_author_group(entry):
        author_name = entry.source_author_rel.name if entry.source_author_rel else (entry.author or 'Unknown')
        if author_name in major_authors:
            return author_name
        return 'Other'

    books = defaultdict(lambda: defaultdict(lambda: {
        'entries': 0,
        'word_count': 0,
        'group_counts': defaultdict(int),
        'title': None,
        'translation_title': None
    }))

    for e in entries:
        book_key = e.book if e.book is not None else 'Unknown'
        chap_key = e.chapter if e.chapter is not None else 'Unknown'
        bucket = books[book_key][chap_key]
        bucket['entries'] += 1
        bucket['word_count'] += e.word_count or 0

        if not bucket['title']:
            bucket['title'] = e.chapter_title or e.title_greek
        if not bucket['translation_title'] and e.translation_title:
            bucket['translation_title'] = e.translation_title

        group = get_school_group(e) if mode == 'school' else get_author_group(e)
        bucket['group_counts'][group] += (e.word_count or 0) or 1

    school_colors = SCHOOL_COLORS.copy()

    author_colors = build_author_colors(authors_set)
    author_colors.setdefault('Other', '#999999')

    colors = school_colors if mode == 'school' else author_colors

    books_list = []
    for book_key, chapters in books.items():
        chapter_items = []
        for chap_key, data in chapters.items():
            dominant = max(data['group_counts'].items(), key=lambda x: x[1])[0] if data['group_counts'] else 'Other'
            chapter_items.append({
                'chapter': chap_key,
                'title': data['title'],
                'translation_title': data['translation_title'],
                'entries': data['entries'],
                'word_count': data['word_count'],
                'dominant_group': dominant,
                'group_breakdown': dict(data['group_counts']),
                'color': colors.get(dominant, '#999999')
            })
        chapter_items.sort(key=lambda c: (9999 if c['chapter'] == 'Unknown' else int(c['chapter']), str(c['chapter'])))
        books_list.append({'book': book_key, 'chapters': chapter_items})

    books_list.sort(key=lambda b: (9999 if b['book'] == 'Unknown' else int(b['book']), str(b['book'])))

    return jsonify({
        'books': books_list,
        'colors': colors,
        'mode': mode,
        'threshold': threshold,
        'groups': list(colors.keys())
    })


@app.route('/api/thematic-structure', methods=['GET'])
def get_thematic_structure():
    """Get the full hierarchical thematic structure"""
    parts = ThematicDivision.query.filter_by(parent_id=None).order_by(ThematicDivision.sort_order).all()
    return jsonify([p.to_dict(include_children=True) for p in parts])


@app.route('/api/thematic-map', methods=['GET'])
def get_thematic_map():
    """
    Get visualization data combining thematic structure with entry statistics.
    """
    mode = request.args.get('mode', 'school')

    divisions = ThematicDivision.query.all()
    entries = Entry.query.all()
    authors_set = {e.source_author_rel.name for e in entries if e.source_author_rel and e.source_author_rel.name}

    # Build division hierarchy to find leaf nodes
    division_children = defaultdict(list)
    for div in divisions:
        if div.parent_id:
            division_children[div.parent_id].append(div.id)

    # Map entries to MOST SPECIFIC (leaf) divisions only
    division_entries = defaultdict(list)
    for entry in entries:
        if entry.book is None:
            continue

        # Find all divisions that cover this entry (book + chapter)
        matching_divs = []
        for div in divisions:
            if div.books_start and div.books_end:
                # Check book range
                if div.books_start <= entry.book <= div.books_end:
                    # If division has chapter range, also check chapter
                    if div.chapter_start is not None and div.chapter_end is not None:
                        if entry.chapter is not None:
                            if div.chapter_start <= entry.chapter <= div.chapter_end:
                                matching_divs.append(div)
                    else:
                        # No chapter range specified, just book range
                        matching_divs.append(div)

        # Filter to only the most specific (those with no children that also match)
        if matching_divs:
            # Sort by specificity (chapter range > book range, smaller = more specific)
            def specificity_key(d):
                has_chapter = 0 if d.chapter_start is not None else 1
                book_range = (d.books_end - d.books_start) if d.books_start is not None and d.books_end is not None else float('inf')
                chapter_range = (d.chapter_end - d.chapter_start) if d.chapter_start is not None and d.chapter_end is not None else float('inf')
                order = d.sort_order if d.sort_order is not None else float('inf')
                return (has_chapter, book_range, chapter_range, order, d.id or 0)

            # Use the most specific division (single assignment to avoid double counting)
            matching_divs.sort(key=specificity_key)

            best_div = None
            for div in matching_divs:
                # Only add if this division has no children that also match
                has_matching_children = False
                for child_id in division_children.get(div.id, []):
                    child = next((d for d in divisions if d.id == child_id), None)
                    if child and child.books_start and child.books_end:
                        if child.books_start <= entry.book <= child.books_end:
                            # Check chapter match too if applicable
                            if child.chapter_start is not None and entry.chapter is not None:
                                if child.chapter_start <= entry.chapter <= child.chapter_end:
                                    has_matching_children = True
                                    break
                            elif child.chapter_start is None:
                                has_matching_children = True
                                break
                if not has_matching_children:
                    best_div = div
                    break

            if best_div:
                division_entries[best_div.id].append(entry)

    def get_group(entry):
        if mode == 'school':
            if entry.source_author_rel:
                name = entry.source_author_rel.name
                if name and 'Galen' in name:
                    return 'Galen'
                sect = entry.source_author_rel.sect
                if sect in ('Pneumatist', 'Methodist', 'Empiricist', 'Dogmatist'):
                    return sect
            return 'Other'
        else:
            return entry.source_author_rel.name if entry.source_author_rel else (entry.author or 'Unknown')

    colors = SCHOOL_COLORS.copy() if mode == 'school' else build_author_colors(authors_set)
    if mode != 'school':
        colors.setdefault('Unknown', '#999999')
        colors.setdefault('Other', '#999999')

    def calc_stats(div_id):
        stats = {'word_count': 0, 'entry_count': 0, 'group_counts': defaultdict(int)}
        for entry in division_entries.get(div_id, []):
            stats['word_count'] += entry.word_count or 0
            stats['entry_count'] += 1
            stats['group_counts'][get_group(entry)] += entry.word_count or 0
        return stats

    def build_tree(division):
        children = [d for d in divisions if d.parent_id == division.id]
        children.sort(key=lambda x: x.sort_order or 0)

        stats = calc_stats(division.id)

        child_data = []
        for child in children:
            cd = build_tree(child)
            child_data.append(cd)
            stats['word_count'] += cd['word_count']
            stats['entry_count'] += cd['entry_count']
            for g, c in cd.get('group_counts', {}).items():
                stats['group_counts'][g] += c

        # Format book range display
        books_display = None
        if division.books_start:
            if division.books_start == division.books_end:
                books_display = f"Book {division.books_start}"
            else:
                books_display = f"Books {division.books_start}-{division.books_end}"

        return {
            'id': division.id,
            'level': division.level,
            'code': division.code,
            'numeral': division.numeral,
            'title_latin': division.title_latin,
            'title_english': division.title_english,
            'definition': division.definition,
            'books': books_display,
            'books_start': division.books_start,
            'books_end': division.books_end,
            'color': division.color,
            'word_count': stats['word_count'],
            'entry_count': stats['entry_count'],
            'group_counts': dict(stats['group_counts']),
            'children': child_data
        }

    roots = [d for d in divisions if d.parent_id is None]
    roots.sort(key=lambda x: x.sort_order or 0)

    return jsonify({
        'structure': [build_tree(r) for r in roots],
        'mode': mode,
        'colors': colors
    })


@app.route('/api/seed-thematic', methods=['POST'])
def seed_thematic_structure():
    """Populate the thematic divisions from Oribasius Books 1-10 structure"""

    # Clear existing
    ThematicDivision.query.delete()
    db.session.commit()

    # Color scheme for four divisions
    div_colors = {
        'ingested': '#dc2626',    # Red
        'activity': '#2563eb',    # Blue
        'evacuated': '#16a34a',   # Green
        'external': '#9333ea'     # Purple
    }

    # Part I: The Material Part (Books 1-10)
    part1 = ThematicDivision(
        level='part', numeral='I', code='I',
        title_latin='To Hylikon',
        title_english='The Material Part',
        definition='An inventory of the physician\'s resources ("The Toolbox"), organized by the Four-Fold Division of Material Causes.',
        books_start=1, books_end=10,
        color='#1e40af', sort_order=1
    )
    db.session.add(part1)
    db.session.flush()

    # ===== DIVISION I: THINGS INGESTED (Books 1-5) =====
    div_i = ThematicDivision(
        level='division', parent_id=part1.id,
        numeral='I', code='I.1',
        title_latin='Ta Prospheromena',
        title_english='Things Ingested',
        definition='Substances taken into the body to nourish, alter, or affect fluids.',
        books_start=1, books_end=5,
        color=div_colors['ingested'], sort_order=1
    )
    db.session.add(div_i)
    db.session.flush()

    # Subdivision A: Inventory of Foodstuffs (Books 1-2)
    subdiv_ia = ThematicDivision(
        level='subdivision', parent_id=div_i.id,
        numeral='A', code='I.1.A',
        title_latin='Materia Medica',
        title_english='The Inventory of Foodstuffs',
        books_start=1, books_end=2,
        color='#ef4444', sort_order=1
    )
    db.session.add(subdiv_ia)
    db.session.flush()

    # Book 1 sections with chapter ranges
    book1_sections = [
        ('Cereals & Grains', 'Wheat, barley, groats, starch, and their properties', 1, 1, 16, 1),
        ('Legumes', 'Lentils, beans, chickpeas, lupines', 1, 17, 28, 2),
        ('Seeds', 'Sesame, poppy, flax', 1, 29, 34, 3),
        ('Garden Fruits', 'Pumpkins, melons, cucumbers', 1, 35, 39, 4),
        ('Tree Fruits', 'Figs, grapes, raisins, mulberries, apples, pears, dates, nuts, olives', 1, 40, 65, 5),
    ]
    for title, defn, book, ch_start, ch_end, order in book1_sections:
        db.session.add(ThematicDivision(
            level='section', parent_id=subdiv_ia.id,
            code=f'I.1.A.1.{order}', title_english=title, definition=defn,
            books_start=book, books_end=book,
            chapter_start=ch_start, chapter_end=ch_end,
            color='#fca5a5', sort_order=order
        ))

    # Book 2 sections with chapter ranges (continuing from Book 1 numbering in original text)
    book2_sections = [
        ('Pot-herbs & Wild Plants', 'Lettuce, mallow, beet, cabbage, asparagus, roots', 2, 1, 28, 1),
        ('Meats', 'Pork, beef, goat; differences between wild and domesticated animals', 2, 29, 29, 2),
        ('Animal Parts', 'Snails, feet, tongue, glands, kidneys, brain, marrow, liver', 2, 30, 41, 3),
        ('Birds', 'Poultry, geese, eggs', 2, 42, 46, 4),
        ('Aquatic Animals', 'Fish (rock vs. pelagic), shellfish, crustaceans, cetaceans', 2, 47, 59, 5),
        ('Dairy', 'Milk and cheese', 2, 60, 62, 6),
        ('Honey', 'Varieties and qualities', 2, 63, 69, 7),
    ]
    for title, defn, book, ch_start, ch_end, order in book2_sections:
        db.session.add(ThematicDivision(
            level='section', parent_id=subdiv_ia.id,
            code=f'I.1.A.2.{order}', title_english=title, definition=defn,
            books_start=book, books_end=book,
            chapter_start=ch_start, chapter_end=ch_end,
            color='#fca5a5', sort_order=10+order
        ))

    # Subdivision B: Classification by Faculty (Book 3)
    subdiv_ib = ThematicDivision(
        level='subdivision', parent_id=div_i.id,
        numeral='B', code='I.1.B',
        title_english='Classification by Faculty',
        definition='The "Powers" of Foods - materials reorganized by their causal effect on the body.',
        books_start=3, books_end=3,
        color='#f87171', sort_order=2
    )
    db.session.add(subdiv_ib)
    db.session.flush()

    book3_sections = [
        ('By Consistency/Humor', 'Thinning, Thickening, Intermediate, Viscous (ID 136-140)', 3, 1),
        ('By Quality of Juice', 'Raw, Cold, Phlegmatic, Melancholic, Bilious (ID 141-145)', 3, 2),
        ('By Nutritional Value', 'Excessive/Superfluous vs. Non-excessive; High vs. Low nourishment (ID 146-149)', 3, 3),
        ('By Digestibility', 'Good/Bad Juices, Easy/Hard to Digest (ID 150-153)', 3, 4),
        ('By Action', 'Strengthening, Head-harming, Flatulent, Carminative (ID 154-158)', 3, 5),
        ('By Pharmacological Action', 'Purging/Cutting, Obstructing, Laxative vs. Binding, Heating/Cooling/Drying/Moistening (ID 159-169)', 3, 6),
    ]
    for title, defn, book, order in book3_sections:
        db.session.add(ThematicDivision(
            level='section', parent_id=subdiv_ib.id,
            code=f'I.1.B.{order}', title_english=title, definition=defn,
            books_start=book, books_end=book, color='#fecaca', sort_order=order
        ))

    # Subdivision C: Preparation of Ingestibles (Books 4-5)
    subdiv_ic = ThematicDivision(
        level='subdivision', parent_id=div_i.id,
        numeral='C', code='I.1.C',
        title_english='Preparation of Ingestibles',
        books_start=4, books_end=5,
        color='#fb7185', sort_order=3
    )
    db.session.add(subdiv_ic)
    db.session.flush()

    # Book 4
    db.session.add(ThematicDivision(
        level='section', parent_id=subdiv_ic.id,
        code='I.1.C.4', title_english='Processing of Grains',
        definition='Breads & Meals: Preparation of wheat, barley, groats, and starch for invalids. Cooking techniques including boiling (ID 170-180)',
        books_start=4, books_end=4, color='#fda4af', sort_order=1
    ))

    # Book 5
    book5_sections = [
        ('Water', 'Choice, purification, and correction of waters (ID 181-185)', 5, 1),
        ('Wine', 'Varieties (watery, sweet, astringent) and their physiological effects (ID 186-187, 193, 206-207)', 5, 2),
        ('Medicinal Drinks', 'Hydromel, Oxymel, Rose-honey, and wine infusions (ID 194-205, 213)', 5, 3),
    ]
    for title, defn, book, order in book5_sections:
        db.session.add(ThematicDivision(
            level='section', parent_id=subdiv_ic.id,
            code=f'I.1.C.5.{order}', title_english=title, definition=defn,
            books_start=book, books_end=book, color='#fda4af', sort_order=10+order
        ))

    # ===== DIVISION II: THINGS DONE (Book 6) =====
    div_ii = ThematicDivision(
        level='division', parent_id=part1.id,
        numeral='II', code='I.2',
        title_latin='Ta Poioumena',
        title_english='Things Done',
        definition='Voluntary and involuntary activities that regulate the body\'s heat, tone, and residues.',
        books_start=6, books_end=6,
        color=div_colors['activity'], sort_order=2
    )
    db.session.add(div_ii)
    db.session.flush()

    book6_sections = [
        ('Rest & Posture', 'Lying down, rest, fasting (ID 214-216)', 6, 1),
        ('States of Consciousness', 'Sleep and Waking (ID 217-219)', 6, 2),
        ('Vocalization', 'Speech and vocalisations as exercise (ID 220-223)', 6, 3),
        ('Massage (Friction)', 'Preparatory and restorative massage (ID 226, 229-233)', 6, 4),
        ('Gymnastics (General)', 'Theory of motion, timing of exercise (ID 224-225, 227-228)', 6, 5),
        ('Specific Exercises', 'Walking, Running, Swinging/Passive Motion, Hoop-rolling, Swimming, Wrestling/Boxing/Ball Games, Armed Combat (ID 234-249)', 6, 6),
        ('Sexual Activity', 'Aphrodisia as a form of evacuation/motion (ID 250-251)', 6, 7),
    ]
    for title, defn, book, order in book6_sections:
        db.session.add(ThematicDivision(
            level='section', parent_id=div_ii.id,
            code=f'I.2.{order}', title_english=title, definition=defn,
            books_start=book, books_end=book, color='#93c5fd', sort_order=order
        ))

    # ===== DIVISION III: THINGS EVACUATED (Books 7-8) =====
    div_iii = ThematicDivision(
        level='division', parent_id=part1.id,
        numeral='III', code='I.3',
        title_latin='Ta Kenoumena',
        title_english='Things Evacuated',
        definition='Tools and methods for removing substances (blood or humors) from the body.',
        books_start=7, books_end=8,
        color=div_colors['evacuated'], sort_order=3
    )
    db.session.add(div_iii)
    db.session.flush()

    # Subdivision A: Vascular and Surface Evacuation (Book 7)
    subdiv_iiia = ThematicDivision(
        level='subdivision', parent_id=div_iii.id,
        numeral='A', code='I.3.A',
        title_english='Vascular and Surface Evacuation',
        definition='Surgery and Bloodletting',
        books_start=7, books_end=7,
        color='#4ade80', sort_order=1
    )
    db.session.add(subdiv_iiia)
    db.session.flush()

    book7_sections = [
        ('Theory of Plethora', 'Indications for evacuation (ID 252-253)', 7, 1),
        ('Venesection', 'Sites, timing, quantity, and technique (ID 254-258, 260-263)', 7, 2),
        ('Arteriotomy', 'Cutting arteries for chronic head pain (ID 264-265)', 7, 3),
        ('Surface Evacuation', 'Cupping glasses, Scarification, Leeches (ID 266-273)', 7, 4),
    ]
    for title, defn, book, order in book7_sections:
        db.session.add(ThematicDivision(
            level='section', parent_id=subdiv_iiia.id,
            code=f'I.3.A.{order}', title_english=title, definition=defn,
            books_start=book, books_end=book, color='#86efac', sort_order=order
        ))

    # Subdivision B: Visceral Evacuation (Book 8)
    subdiv_iiib = ThematicDivision(
        level='subdivision', parent_id=div_iii.id,
        numeral='B', code='I.3.B',
        title_english='Visceral Evacuation',
        definition='The Pharmaceutical "Cleanse"',
        books_start=8, books_end=8,
        color='#22c55e', sort_order=2
    )
    db.session.add(subdiv_iiib)
    db.session.flush()

    book8_sections = [
        ('Purgatives', 'Theory of purging, Hellebore (preparation and dosage), Scammony, Aloe (ID 274-286, 320-328)', 8, 1),
        ('Head & Respiratory', 'Sternutatories (sneezing), Dephlegmation, Fumigation (ID 287-290)', 8, 2),
        ('Specific Systems', 'Diuretics, Emmenagogues, Diaphoretics (ID 292-294)', 8, 3),
        ('Mechanisms', 'Diversion and Counter-irritation (ID 295-296)', 8, 4),
        ('Emetics', 'Vomiting on an empty stomach vs. after food (ID 297-300)', 8, 5),
        ('Enemas', 'Suppositories and Clysters (soothing vs. acrid) (ID 301-317)', 8, 6),
    ]
    for title, defn, book, order in book8_sections:
        db.session.add(ThematicDivision(
            level='section', parent_id=subdiv_iiib.id,
            code=f'I.3.B.{order}', title_english=title, definition=defn,
            books_start=book, books_end=book, color='#bbf7d0', sort_order=order
        ))

    # ===== DIVISION IV: THINGS APPLIED EXTERNALLY (Books 9-10) =====
    div_iv = ThematicDivision(
        level='division', parent_id=part1.id,
        numeral='IV', code='I.4',
        title_latin='Ta Exōthen Prospiptonta',
        title_english='Things Applied Externally',
        definition='Substances and forces that contact the surface of the body.',
        books_start=9, books_end=10,
        color=div_colors['external'], sort_order=4
    )
    db.session.add(div_iv)
    db.session.flush()

    # Subdivision A: Ambient Environment (Book 9 Part 1)
    subdiv_iva = ThematicDivision(
        level='subdivision', parent_id=div_iv.id,
        numeral='A', code='I.4.A',
        title_english='Ambient Environment',
        definition='The "Fine" Externals - Air and Location',
        books_start=9, books_end=9,
        color='#a855f7', sort_order=1
    )
    db.session.add(subdiv_iva)
    db.session.flush()

    db.session.add(ThematicDivision(
        level='section', parent_id=subdiv_iva.id,
        code='I.4.A.1', title_english='Air',
        definition='Quality of air, seasonal changes (Spring, Summer, etc.), and daily/monthly variations (ID 329-333)',
        books_start=9, books_end=9, color='#c084fc', sort_order=1
    ))
    db.session.add(ThematicDivision(
        level='section', parent_id=subdiv_iva.id,
        code='I.4.A.2', title_english='Place',
        definition='Impact of city vs. country, altitude, soil types, and wind direction (ID 334-348)',
        books_start=9, books_end=9, color='#c084fc', sort_order=2
    ))

    # Subdivision B: Topical Therapeutics (Book 9 Part 2 + Book 10)
    subdiv_ivb = ThematicDivision(
        level='subdivision', parent_id=div_iv.id,
        numeral='B', code='I.4.B',
        title_english='Topical Therapeutics',
        definition='The "Coarse" Externals',
        books_start=9, books_end=10,
        color='#9333ea', sort_order=2
    )
    db.session.add(subdiv_ivb)
    db.session.flush()

    # Book 9 Part 2: Poultices
    db.session.add(ThematicDivision(
        level='section', parent_id=subdiv_ivb.id,
        code='I.4.B.9', title_english='Poultices (Kataplasmata)',
        definition='General theory of fomentations and poultices. Specific ingredients: bread, bran, barley, flaxseed, figs, beans, lentils, dates, etc. (ID 349-383)',
        books_start=9, books_end=9, color='#d8b4fe', sort_order=1
    ))

    # Book 10 sections
    book10_sections = [
        ('Baths', 'Theory of freshwater baths, Prepared/Artificial baths, Natural/Mineral springs (ID 384-388)', 10, 1),
        ('Specialized Baths', 'Cold bathing, Oil immersion, Sand baths, Sunbathing (ID 389-392)', 10, 2),
        ('Skin & Surface', 'Cauterization, Depilatories (Dropax/Psilothron), Shaving, Combing (ID 393-400)', 10, 3),
        ('Local Applications', 'Constriction/Binding, Inhalants, Ointments/Smegmata, Styptics (ID 401-406)', 10, 4),
        ('Orificial Applications', 'Collyria (eyes), Trochisks, Pessaries, Infusions (ID 407-410)', 10, 5),
        ('Rubs/Salves', 'Anointing for specific organs (ears, teeth) (ID 411-420)', 10, 6),
    ]
    for title, defn, book, order in book10_sections:
        db.session.add(ThematicDivision(
            level='section', parent_id=subdiv_ivb.id,
            code=f'I.4.B.10.{order}', title_english=title, definition=defn,
            books_start=book, books_end=book, color='#d8b4fe', sort_order=10+order
        ))

    db.session.commit()

    count = ThematicDivision.query.count()
    return jsonify({'message': f'Seeded {count} thematic divisions'})

@app.route('/api/compare', methods=['GET'])
def compare_authors():
    """Compare word counts between two authors/groups"""
    type1 = request.args.get('type1', 'author')  # author, author_group, book
    value1 = request.args.get('value1')
    type2 = request.args.get('type2', 'author')
    value2 = request.args.get('value2')
    
    def get_stats(filter_type, filter_value):
        query = Entry.query
        if filter_type == 'author':
            query = query.filter(Entry.author == filter_value)
        elif filter_type == 'author_group':
            query = query.filter(Entry.author_group == filter_value)
        elif filter_type == 'book':
            query = query.filter(Entry.book == int(filter_value))
        
        entries = query.all()
        total_words = sum(e.word_count or 0 for e in entries)
        return {
            'name': filter_value,
            'type': filter_type,
            'total_words': total_words,
            'entry_count': len(entries),
            'avg_words_per_entry': total_words / len(entries) if entries else 0
        }
    
    return jsonify({
        'item1': get_stats(type1, value1),
        'item2': get_stats(type2, value2)
    })

@app.route('/api/history/<int:entry_id>', methods=['GET'])
def get_entry_history(entry_id):
    """Get edit history for an entry"""
    history = EditHistory.query.filter_by(entry_id=entry_id).order_by(EditHistory.edited_at.desc()).all()
    return jsonify([{
        'id': h.id,
        'field_changed': h.field_changed,
        'old_value': h.old_value[:200] + '...' if h.old_value and len(h.old_value) > 200 else h.old_value,
        'new_value': h.new_value[:200] + '...' if h.new_value and len(h.new_value) > 200 else h.new_value,
        'editor_name': h.editor_name,
        'edited_at': h.edited_at.isoformat()
    } for h in history])

@app.route('/api/export', methods=['GET'])
def export_csv():
    """Export current data to CSV"""
    entries = Entry.query.order_by(Entry.book, Entry.chapter).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        'ID', 'Author Named', 'Author', 'Book', 'Chapter', 'Chapter Title', 'Title (Greek)', 
        'Body (Greek)', 'Translation Title', 'Translation Content', 'Location',
        'Word Count', 'Note 1', 'Note 2', 'Note 3', 'Note 4', 
        'Author Group', 'Pneumatist', 'Themes', 'URN'
    ])
    
    for e in entries:
        writer.writerow([
            e.id, e.author_named, e.author, e.book, e.chapter, e.chapter_title, e.title_greek,
            e.body_greek, e.translation_title, e.translation_content, e.location,
            e.word_count, e.note1, e.note2, e.note3, e.note4,
            e.author_group, e.pneumatist, e.themes, e.urn
        ])
    
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'oribasius_export_{datetime.now().strftime("%Y%m%d")}.csv'
    )

@app.route('/api/import', methods=['POST'])
def import_csv():
    """Import data from CSV"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'File must be a CSV'}), 400
    
    content = file.read().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return jsonify({'error': 'CSV missing header row'}), 400

    def normalize_header(name):
        return re.sub(r'[^a-z0-9]+', '_', name.strip().lower())

    field_lookup = {normalize_header(name): name for name in reader.fieldnames}

    def get_value(row, *candidates):
        for candidate in candidates:
            key = field_lookup.get(normalize_header(candidate))
            if key is None:
                continue
            value = row.get(key)
            if value is not None:
                value = value.strip()
                if value:
                    return value
        return None

    def parse_int(value):
        if value is None:
            return None
        value = str(value).strip()
        if not value:
            return None
        try:
            return int(float(value))
        except ValueError:
            return None

    author_cache = {}
    count = 0
    new_authors = 0

    for row in reader:
        author_named = get_value(row, 'Author Named', 'author_named')
        author_name = get_value(row, 'Author', 'author')
        author_group = get_value(row, 'Author Group', 'author_group')
        book = parse_int(get_value(row, 'Book', 'book'))
        chapter_raw = get_value(row, 'Chapter', 'chapter')
        chapter_title = get_value(row, 'Chapter Title', 'chapter_title')
        chapter = parse_int(chapter_raw)
        if chapter is not None and chapter <= 0:
            chapter = None
        if not chapter_title and chapter is None and chapter_raw:
            chapter_title = chapter_raw.strip()
        section = parse_int(get_value(row, 'Section', 'section'))
        raeder_volume = get_value(row, 'Raeder Volume', 'raeder_volume')
        raeder_page = parse_int(get_value(row, 'Raeder Page', 'raeder_page'))
        raeder_line_start = parse_int(get_value(row, 'Line Start', 'raeder_line_start'))
        raeder_line_end = parse_int(get_value(row, 'Line End', 'raeder_line_end'))
        title_greek = get_value(row, 'Title', 'title_greek', 'Greek Title')
        body_greek = get_value(row, 'Body', 'body_greek')
        translation_title = get_value(row, 'Translation_Title', 'Translation Title', 'translation_title')
        translation_content = get_value(row, 'Translation_content', 'Translation Content', 'translation_content')
        location = get_value(row, 'Location', 'location')
        note1 = get_value(row, 'Note', 'note1')
        note2 = get_value(row, 'Note2', 'note2')
        note3 = get_value(row, 'Note3', 'note3')
        note4 = get_value(row, 'Note4', 'note4')
        word_count = parse_int(get_value(row, 'Word Count', 'word_count'))
        pneumatist_value = get_value(row, 'Pneumatist (+ Antyllus)', 'Pneumatist', 'Medical Sect', 'Sect', 'pneumatist')
        sect_value = get_value(row, 'Medical Sect', 'Sect', 'Pneumatist (+ Antyllus)', 'Pneumatist')

        source_author = None
        if author_name:
            key = author_name.strip().lower()
            if key not in author_cache:
                existing = SourceAuthor.query.filter(db.func.lower(SourceAuthor.name) == key).first()
                if existing:
                    author_cache[key] = existing
                else:
                    cleaned_sect = sect_value.strip() if sect_value else None
                    sect_certain = True
                    if cleaned_sect and cleaned_sect.endswith('?'):
                        cleaned_sect = cleaned_sect.rstrip(' ?')
                        sect_certain = False
                    new_author = SourceAuthor(
                        name=author_name.strip(),
                        sect=cleaned_sect or 'Unknown',
                        sect_certain=sect_certain
                    )
                    db.session.add(new_author)
                    db.session.flush()
                    author_cache[key] = new_author
                    new_authors += 1
            source_author = author_cache.get(key)

        entry = Entry(
            author_named=author_named,
            author=author_name,
            source_author_id=source_author.id if source_author else None,
            author_group=author_group,
            book=book,
            chapter=chapter,
            chapter_title=chapter_title,
            section=section,
            raeder_volume=raeder_volume,
            raeder_page=raeder_page,
            raeder_line_start=raeder_line_start,
            raeder_line_end=raeder_line_end,
            title_greek=title_greek,
            body_greek=body_greek,
            translation_title=translation_title,
            translation_content=translation_content,
            location=location,
            word_count=word_count or 0,
            note1=note1,
            note2=note2,
            note3=note3,
            note4=note4,
            pneumatist=pneumatist_value
        )

        if entry.body_greek:
            entry.lemma_index = build_lemma_index(entry.body_greek)
            if not word_count:
                entry.word_count = len(re.findall(r'\S+', entry.body_greek))
        entry.generate_urns()

        db.session.add(entry)
        count += 1

    db.session.commit()
    msg = f"Imported {count} entries"
    if new_authors:
        msg += f" and created {new_authors} source author(s)"
    return jsonify({'message': msg})

@app.route('/api/themes', methods=['GET'])
def get_themes():
    themes = Theme.query.all()
    return jsonify([{'id': t.id, 'name': t.name, 'description': t.description, 'color': t.color} for t in themes])

@app.route('/api/themes', methods=['POST'])
def create_theme():
    data = request.json
    theme = Theme(name=data['name'], description=data.get('description', ''), color=data.get('color', '#6366f1'))
    db.session.add(theme)
    db.session.commit()
    return jsonify({'id': theme.id, 'name': theme.name, 'description': theme.description, 'color': theme.color}), 201


@app.route('/api/reset', methods=['POST'])
def reset_database():
    """Delete entries (and optionally related data) to allow clean imports"""
    data = request.json or {}
    scope = data.get('scope', 'entries')
    confirm = data.get('confirm')
    if confirm != 'RESET':
        return jsonify({'error': 'Confirmation required'}), 400

    try:
        db.session.execute(entry_ingredients.delete())
        EditHistory.query.delete()
        Entry.query.delete()
        message = 'Cleared all entries'

        if scope == 'all':
            Ingredient.query.delete()
            SourceAuthor.query.delete()
            Theme.query.delete()
            message = 'Cleared all entries, ingredients, source authors, and themes'

        db.session.commit()
        if scope == 'all':
            # Recreate schema helpers so future imports work smoothly
            bootstrap_source_authors()
            link_entries_to_source_authors()
        return jsonify({'message': message})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': f'Failed to reset: {exc}'}), 500

# URN generation helper
@app.route('/api/generate-urn/<int:entry_id>', methods=['POST'])
def generate_urn(entry_id):
    """Generate CTS and Raeder URNs for an entry"""
    entry = Entry.query.get_or_404(entry_id)
    entry.generate_urns()
    db.session.commit()
    return jsonify({'urn_cts': entry.urn_cts, 'urn_raeder': entry.urn_raeder})

@app.route('/api/reindex-lemmas', methods=['POST'])
def reindex_lemmas():
    """Rebuild lemma indices for all entries"""
    entries = Entry.query.all()
    count = 0
    for entry in entries:
        if entry.body_greek:
            entry.lemma_index = build_lemma_index(entry.body_greek)
            count += 1
    db.session.commit()
    return jsonify({'message': f'Reindexed {count} entries'})

@app.route('/api/generate-all-urns', methods=['POST'])
def generate_all_urns():
    """Generate URNs for all entries"""
    entries = Entry.query.all()
    count = 0
    for entry in entries:
        entry.generate_urns()
        count += 1
    db.session.commit()
    return jsonify({'message': f'Generated URNs for {count} entries'})


def build_author_colors(authors_set):
    """Consistent author color mapping across visualizations"""
    author_colors = {}
    for idx, name in enumerate(sorted(authors_set)):
        author_colors[name] = AUTHOR_PALETTE[idx % len(AUTHOR_PALETTE)]
    return author_colors


def run_schema_migrations():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    if 'entries' in tables:
        columns = {col['name'] for col in inspector.get_columns('entries')}
        if 'chapter_title' not in columns:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE entries ADD COLUMN chapter_title VARCHAR(100)'))


def bootstrap_source_authors():
    existing = {a.name.strip().lower() for a in SourceAuthor.query.all() if a.name}
    rows = db.session.query(Entry.author, db.func.max(Entry.pneumatist)) \
        .filter(Entry.author.isnot(None), Entry.author != '').group_by(Entry.author).all()
    created = 0
    for author_name, pneumatist in rows:
        if not author_name:
            continue
        normalized = author_name.strip().lower()
        if not normalized:
            continue
        if normalized in existing:
            continue
        source_author = SourceAuthor(
            name=author_name.strip(),
            sect=pneumatist.strip() if pneumatist else 'Unknown',
            sect_certain=True
        )
        db.session.add(source_author)
        existing.add(normalized)
        created += 1
    if created:
        db.session.commit()


def link_entries_to_source_authors():
    mapping = {a.name.strip().lower(): a.id for a in SourceAuthor.query.all() if a.name}
    if not mapping:
        return
    updated = 0
    entries = Entry.query.filter(
        Entry.source_author_id.is_(None),
        Entry.author.isnot(None),
        Entry.author != ''
    ).all()
    for entry in entries:
        key = entry.author.strip().lower()
        if not key:
            continue
        if key in mapping:
            entry.source_author_id = mapping[key]
            updated += 1
    if updated:
        db.session.commit()


def init_db():
    with app.app_context():
        db.create_all()
        run_schema_migrations()
        bootstrap_source_authors()
        link_entries_to_source_authors()
        log_db_info(app.config['SQLALCHEMY_DATABASE_URI'])


init_db()

# Demo mode: allow users to “edit” but discard changes (no persistence)
if app.config['DEMO_MODE']:
    real_commit = db.session.commit

    def demo_commit():
        db.session.flush()  # ensure IDs are assigned for responses
        db.session.rollback()
    db.session.commit = demo_commit


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
