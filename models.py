from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    """Customer user accounts"""
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False, unique=True)
    password_hash = db.Column(db.String(256), nullable=False)
    phone = db.Column(db.String(20))
    date_of_birth = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    # Relationship to bookings
    bookings = db.relationship('Booking', backref='user', lazy=True)

    def set_password(self, password):
        """Hash and set the password"""
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        """Check if password matches"""
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.email}>'


class Category(db.Model):
    """Categories for organizing services"""
    __tablename__ = 'category'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    display_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    services = db.relationship('Service', backref='category', lazy=True)

    def __repr__(self):
        return f'<Category {self.name}>'


class Service(db.Model):
    """Services offered for booking"""
    __tablename__ = 'service'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, default=0.0)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    bookings = db.relationship('Booking', backref='service', lazy=True)

    def __repr__(self):
        return f'<Service {self.name}>'


class Availability(db.Model):
    """Working hours/availability settings by day of week"""
    __tablename__ = 'availability'

    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Monday, 6=Sunday
    start_time = db.Column(db.String(5), nullable=False)  # "09:00"
    end_time = db.Column(db.String(5), nullable=False)    # "17:00"
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        return f'<Availability {days[self.day_of_week]} {self.start_time}-{self.end_time}>'


class Booking(db.Model):
    """Customer bookings"""
    __tablename__ = 'booking'

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Nullable for guest bookings

    # Customer info
    customer_name = db.Column(db.String(100), nullable=False)
    customer_email = db.Column(db.String(120), nullable=False)
    customer_phone = db.Column(db.String(20))

    # Booking details - store both start and end times
    booking_date = db.Column(db.Date, nullable=False)
    booking_time = db.Column(db.String(5), nullable=False)  # Start time "09:00"
    end_time = db.Column(db.String(5), nullable=False)      # End time "09:30"

    # Status: confirmed, cancelled, completed, no_show
    status = db.Column(db.String(20), default='confirmed')
    no_show_at = db.Column(db.DateTime, nullable=True)  # When marked as no-show
    notes = db.Column(db.Text)

    # Email tracking
    confirmation_sent = db.Column(db.Boolean, default=False)
    reminder_sent = db.Column(db.Boolean, default=False)
    followup_sent = db.Column(db.Boolean, default=False)
    day_after_sent = db.Column(db.Boolean, default=False)
    day_after_blocked = db.Column(db.Boolean, default=False)  # Block this booking from 24hr email

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Link to intake form
    intake_form_id = db.Column(db.Integer, db.ForeignKey('intake_form.id'), nullable=True)
    intake_form = db.relationship('IntakeForm', backref='booking', uselist=False)

    def __repr__(self):
        return f'<Booking {self.customer_name} - {self.booking_date} {self.booking_time}>'


class IntakeForm(db.Model):
    """Client intake form for personal information and declaration"""
    __tablename__ = 'intake_form'

    id = db.Column(db.Integer, primary_key=True)

    # Personal Information
    full_name = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.Text)

    # Age Verification
    is_minor = db.Column(db.Boolean, default=False)
    id_type = db.Column(db.String(50))  # Driver's License, Passport, etc.
    parent_guardian_name = db.Column(db.String(100))  # Required if minor
    parent_guardian_phone = db.Column(db.String(20))  # Required if minor
    parental_consent = db.Column(db.Boolean, default=False)  # Required if minor

    # Declaration
    declaration_confirmed = db.Column(db.Boolean, default=False)

    # Admin notes
    admin_notes = db.Column(db.Text)
    reviewed_by_admin = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<IntakeForm {self.full_name} - {self.created_at}>'


class BlockedTime(db.Model):
    """Blocked time slots for breaks, lunch, days off, etc."""
    __tablename__ = 'blocked_time'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(5), nullable=True)  # "12:00" - null means all day
    end_time = db.Column(db.String(5), nullable=True)    # "13:00" - null means all day
    reason = db.Column(db.String(100))  # "Lunch", "Break", "Day Off", etc.
    is_all_day = db.Column(db.Boolean, default=False)
    is_recurring_weekly = db.Column(db.Boolean, default=False)  # For recurring breaks like daily lunch
    recurring_day_of_week = db.Column(db.Integer, nullable=True)  # 0=Monday, 6=Sunday (for recurring)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        if self.is_all_day:
            return f'<BlockedTime {self.date} ALL DAY - {self.reason}>'
        return f'<BlockedTime {self.date} {self.start_time}-{self.end_time} - {self.reason}>'


class Settings(db.Model):
    """Application settings (key-value store)"""
    __tablename__ = 'settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text)

    # Default settings
    DEFAULTS = {
        # Business info
        'business_name': 'White Thorn Piercing',
        'business_email': '',
        'business_phone': '',
        'business_address': '',

        # Email settings
        'email_enabled': 'false',
        'smtp_server': '',
        'smtp_port': '587',
        'smtp_username': '',
        'smtp_password': '',
        'smtp_use_tls': 'true',

        # Notification settings
        'send_confirmation_email': 'true',
        'send_reminder_email': 'true',
        'reminder_hours_before': '24',  # Hours before appointment to send reminder
    }

    @classmethod
    def get(cls, key, default=None):
        """Get a setting value"""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            return setting.value
        return cls.DEFAULTS.get(key, default)

    @classmethod
    def set(cls, key, value):
        """Set a setting value"""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = cls(key=key, value=value)
            db.session.add(setting)
        db.session.commit()

    @classmethod
    def get_bool(cls, key):
        """Get a boolean setting"""
        return cls.get(key, 'false').lower() == 'true'

    @classmethod
    def get_int(cls, key, default=0):
        """Get an integer setting"""
        try:
            return int(cls.get(key, str(default)))
        except (ValueError, TypeError):
            return default

    def __repr__(self):
        return f'<Settings {self.key}={self.value}>'


class Aftercare(db.Model):
    """Aftercare advice content for services"""
    __tablename__ = 'aftercare'

    id = db.Column(db.Integer, primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'), nullable=True)  # Nullable for general advice
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to service
    service = db.relationship('Service', backref='aftercare_guides', lazy=True)

    def __repr__(self):
        return f'<Aftercare {self.title}>'


class ClientNote(db.Model):
    """Admin notes for clients - visible only to staff, never to customers"""
    __tablename__ = 'client_note'

    id = db.Column(db.Integer, primary_key=True)
    client_email = db.Column(db.String(120), nullable=False, index=True)  # Link by email
    client_name = db.Column(db.String(100))  # Store name for reference
    note = db.Column(db.Text, nullable=False)
    is_alert = db.Column(db.Boolean, default=False)  # Important notes to highlight
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<ClientNote {self.client_email}>'
