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

    services = db.relationship('Service', backref='category', lazy=True, order_by='Service.display_order')

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

        # Email settings (legacy SMTP - deprecated)
        'email_enabled': 'false',
        'smtp_server': '',
        'smtp_port': '587',
        'smtp_username': '',
        'smtp_password': '',
        'smtp_use_tls': 'true',

        # Email API settings (Brevo)
        'email_provider': 'brevo',  # 'brevo' or 'smtp' (legacy)
        'brevo_api_key': '',
        'email_from_address': '',
        'email_from_name': 'White Thorn Piercing',

        # Notification settings
        'send_confirmation_email': 'true',
        'send_reminder_email': 'true',
        'reminder_hours_before': '24',  # Hours before appointment to send reminder
        'send_followup_email': 'true',
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
    def get_bool(cls, key, default=False):
        """Get a boolean setting"""
        value = cls.get(key)
        if value is None:
            return default
        return value.lower() == 'true'

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


class Client(db.Model):
    """Consolidated client records for CRM and email marketing"""
    __tablename__ = 'client'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), index=True)
    phone = db.Column(db.String(20), index=True)
    name = db.Column(db.String(100))

    # Source tracking
    source = db.Column(db.String(50), default='booking')  # 'booking', 'import', 'manual'

    # Email marketing
    email_opt_in = db.Column(db.Boolean, default=True)
    unsubscribe_token = db.Column(db.String(64), unique=True, index=True)
    unsubscribed_at = db.Column(db.DateTime, nullable=True)

    # Stats
    total_bookings = db.Column(db.Integer, default=0)
    last_booking_date = db.Column(db.DateTime, nullable=True)

    # Additional info
    notes = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tags = db.relationship('ClientTag', secondary='client_tag_assignment', backref='clients')

    def __repr__(self):
        return f'<Client {self.name} - {self.email}>'

    @classmethod
    def find_or_create(cls, email=None, phone=None, name=None, source='booking'):
        """Find existing client by email OR phone, or create new one"""
        import secrets

        client = None

        # Try to find by email first
        if email:
            client = cls.query.filter_by(email=email).first()

        # If not found, try by phone
        if not client and phone:
            # Normalize phone for comparison
            normalized_phone = ''.join(filter(str.isdigit, phone)) if phone else None
            if normalized_phone:
                all_clients = cls.query.filter(cls.phone.isnot(None)).all()
                for c in all_clients:
                    c_phone = ''.join(filter(str.isdigit, c.phone)) if c.phone else ''
                    if c_phone and c_phone == normalized_phone:
                        client = c
                        break

        # Create new client if not found
        if not client:
            client = cls(
                email=email,
                phone=phone,
                name=name,
                source=source,
                unsubscribe_token=secrets.token_urlsafe(32)
            )
            db.session.add(client)
        else:
            # Update name if provided and client name is empty
            if name and not client.name:
                client.name = name
            # Update email if provided and not set
            if email and not client.email:
                client.email = email
            # Update phone if provided and not set
            if phone and not client.phone:
                client.phone = phone

        return client

    def update_booking_stats(self):
        """Update booking statistics for this client"""
        from sqlalchemy import func

        # Count bookings matching this client's email or phone
        query = Booking.query.filter(
            db.or_(
                Booking.customer_email == self.email,
                Booking.customer_phone == self.phone
            ) if self.email and self.phone else (
                Booking.customer_email == self.email if self.email else Booking.customer_phone == self.phone
            )
        ).filter(Booking.status != 'cancelled')

        self.total_bookings = query.count()

        # Get last booking date
        last_booking = query.order_by(Booking.booking_date.desc()).first()
        if last_booking:
            self.last_booking_date = datetime.combine(last_booking.booking_date, datetime.min.time())


class ClientTag(db.Model):
    """Tags for categorizing clients"""
    __tablename__ = 'client_tag'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    color = db.Column(db.String(7), default='#6366f1')  # Hex color
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ClientTag {self.name}>'

    @property
    def client_count(self):
        """Get count of clients with this tag"""
        return len(self.clients)


class ClientTagAssignment(db.Model):
    """Many-to-many relationship between clients and tags"""
    __tablename__ = 'client_tag_assignment'

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    tag_id = db.Column(db.Integer, db.ForeignKey('client_tag.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Ensure unique client-tag pairs
    __table_args__ = (db.UniqueConstraint('client_id', 'tag_id', name='unique_client_tag'),)


class EmailCampaign(db.Model):
    """Email marketing campaigns"""
    __tablename__ = 'email_campaign'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)  # HTML content

    # Status: draft, scheduled, sending, sent, cancelled
    status = db.Column(db.String(20), default='draft')

    # Scheduling
    scheduled_at = db.Column(db.DateTime, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)

    # Targeting
    target_all = db.Column(db.Boolean, default=True)  # Send to all opted-in clients
    target_tag_ids = db.Column(db.Text)  # Comma-separated tag IDs if not target_all

    # Stats
    total_recipients = db.Column(db.Integer, default=0)
    sent_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    recipients = db.relationship('CampaignRecipient', backref='campaign', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<EmailCampaign {self.name} ({self.status})>'

    def get_target_tags(self):
        """Get list of target tag IDs"""
        if not self.target_tag_ids:
            return []
        return [int(tid) for tid in self.target_tag_ids.split(',') if tid]

    def set_target_tags(self, tag_ids):
        """Set target tag IDs from list"""
        self.target_tag_ids = ','.join(str(tid) for tid in tag_ids) if tag_ids else None


class CampaignRecipient(db.Model):
    """Recipients for email campaigns with delivery tracking"""
    __tablename__ = 'campaign_recipient'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('email_campaign.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)

    # Status: pending, sent, failed
    status = db.Column(db.String(20), default='pending')
    error_message = db.Column(db.Text)

    # Timestamps
    sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to client
    client = db.relationship('Client', backref='campaign_recipients')

    # Ensure unique campaign-client pairs
    __table_args__ = (db.UniqueConstraint('campaign_id', 'client_id', name='unique_campaign_client'),)

    def __repr__(self):
        return f'<CampaignRecipient Campaign:{self.campaign_id} Client:{self.client_id} ({self.status})>'


class EmailTemplate(db.Model):
    """Pre-built email templates for campaigns"""
    __tablename__ = 'email_template'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    subject = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)  # HTML content
    category = db.Column(db.String(50))  # 'promotion', 'announcement', 'reengagement'
    is_default = db.Column(db.Boolean, default=False)  # System templates
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<EmailTemplate {self.name}>'


class AdminUser(db.Model):
    """Admin and staff user accounts"""
    __tablename__ = 'admin_user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), nullable=False, unique=True)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(100), nullable=False)  # Display name
    role = db.Column(db.String(20), nullable=False, default='staff')  # 'owner' or 'staff'
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)

    # Relationship to activity logs
    activities = db.relationship('ActivityLog', backref='admin_user', lazy=True)

    def set_password(self, password):
        """Hash and set the password"""
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password):
        """Check if password matches"""
        return check_password_hash(self.password_hash, password)

    def is_owner(self):
        """Check if user is the owner"""
        return self.role == 'owner'

    def __repr__(self):
        return f'<AdminUser {self.username} ({self.role})>'


class ActivityLog(db.Model):
    """Activity log for tracking admin/staff actions"""
    __tablename__ = 'activity_log'

    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('admin_user.id'), nullable=True)
    action_type = db.Column(db.String(50), nullable=False)  # 'booking_created', 'booking_cancelled', etc.
    description = db.Column(db.Text, nullable=False)

    # Optional references to related objects
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=True)
    client_email = db.Column(db.String(120), nullable=True)

    # For tracking what changed
    details = db.Column(db.Text, nullable=True)  # JSON string with additional details

    is_read = db.Column(db.Boolean, default=False)  # For notification bell
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    booking = db.relationship('Booking', backref='activity_logs', lazy=True)

    # Action types
    ACTION_TYPES = {
        'booking_created': 'New Booking',
        'booking_cancelled': 'Booking Cancelled',
        'booking_completed': 'Booking Completed',
        'booking_no_show': 'No Show',
        'booking_rescheduled': 'Booking Rescheduled',
        'client_note_added': 'Client Note Added',
        'client_note_updated': 'Client Note Updated',
        'service_created': 'Service Created',
        'service_updated': 'Service Updated',
        'service_deleted': 'Service Deleted',
        'category_created': 'Category Created',
        'category_updated': 'Category Updated',
        'staff_login': 'Staff Login',
        'owner_login': 'Owner Login',
    }

    @classmethod
    def log(cls, action_type, description, admin_user_id=None, booking_id=None, client_email=None, details=None):
        """Create a new activity log entry"""
        log_entry = cls(
            admin_user_id=admin_user_id,
            action_type=action_type,
            description=description,
            booking_id=booking_id,
            client_email=client_email,
            details=details
        )
        db.session.add(log_entry)
        db.session.commit()
        return log_entry

    def get_icon(self):
        """Get icon for this action type"""
        icons = {
            'booking_created': '📅',
            'booking_cancelled': '❌',
            'booking_completed': '✅',
            'booking_no_show': '👻',
            'booking_rescheduled': '🔄',
            'client_note_added': '📝',
            'client_note_updated': '✏️',
            'service_created': '➕',
            'service_updated': '🔧',
            'service_deleted': '🗑️',
            'category_created': '📁',
            'category_updated': '📂',
            'staff_login': '👤',
            'owner_login': '👑',
        }
        return icons.get(self.action_type, '📋')

    def __repr__(self):
        return f'<ActivityLog {self.action_type} at {self.created_at}>'
