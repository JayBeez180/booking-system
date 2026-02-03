from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, Response, g
from models import db, Service, Availability, Booking, IntakeForm, Settings, Category, BlockedTime, User, Aftercare, ClientNote, AdminUser, ActivityLog
from datetime import datetime, timedelta, date
from functools import wraps
import csv
import io
import os
import threading
import time

# Load environment variables from .env file (for local development)
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# Database configuration - use PostgreSQL in production, SQLite locally
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # Railway uses postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Local development - use SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///booking.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Admin credentials from environment variables
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

db.init_app(app)


def login_required(f):
    """Decorator to require admin login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Please log in to access the admin panel.', 'error')
            return redirect(url_for('admin_login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def owner_required(f):
    """Decorator to require owner role for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Please log in to access the admin panel.', 'error')
            return redirect(url_for('admin_login', next=request.url))
        if session.get('admin_role') != 'owner':
            flash('You do not have permission to access this page.', 'error')
            return redirect(url_for('admin_calendar'))
        return f(*args, **kwargs)
    return decorated_function


def get_current_admin():
    """Get the currently logged in admin user"""
    if session.get('admin_logged_in') and session.get('admin_user_id'):
        return AdminUser.query.get(session.get('admin_user_id'))
    return None


@app.before_request
def load_current_admin():
    """Load current admin user before each request"""
    g.current_admin = get_current_admin()


def time_to_minutes(time_str):
    """Convert time string 'HH:MM' to minutes from midnight"""
    h, m = map(int, time_str.split(':'))
    return h * 60 + m


def minutes_to_time(minutes):
    """Convert minutes from midnight to time string 'HH:MM'"""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def auto_complete_past_appointments():
    """
    Automatically mark confirmed appointments as completed
    if their end time has passed.
    """
    now = datetime.now()
    today = now.date()
    current_time = now.strftime('%H:%M')

    # Get all confirmed bookings that should be completed
    # Either: date is in the past, OR date is today and end_time has passed
    past_bookings = Booking.query.filter(
        Booking.status == 'confirmed'
    ).all()

    completed_count = 0
    for booking in past_bookings:
        # Check if the appointment end time has passed
        if booking.booking_date < today:
            # Past date - mark as completed
            booking.status = 'completed'
            completed_count += 1
        elif booking.booking_date == today and booking.end_time <= current_time:
            # Today but end time has passed - mark as completed
            booking.status = 'completed'
            completed_count += 1

    if completed_count > 0:
        db.session.commit()
        print(f"[AUTO-COMPLETE] Marked {completed_count} appointments as completed")

    return completed_count


def is_time_blocked(booking_date, start_time, end_time):
    """
    Check if a time slot overlaps with any blocked times.
    Returns True if blocked, False if clear.
    """
    start_mins = time_to_minutes(start_time)
    end_mins = time_to_minutes(end_time)
    day_of_week = booking_date.weekday()

    # Check for all-day blocks on this specific date
    all_day_blocks = BlockedTime.query.filter_by(
        date=booking_date,
        is_all_day=True,
        is_recurring_weekly=False
    ).all()

    if all_day_blocks:
        return True

    # Check for recurring all-day blocks on this day of week
    recurring_all_day = BlockedTime.query.filter_by(
        is_recurring_weekly=True,
        recurring_day_of_week=day_of_week,
        is_all_day=True
    ).all()

    if recurring_all_day:
        return True

    # Check for time-specific blocks on this date
    date_blocks = BlockedTime.query.filter(
        BlockedTime.date == booking_date,
        BlockedTime.is_all_day == False,
        BlockedTime.is_recurring_weekly == False
    ).all()

    for block in date_blocks:
        block_start = time_to_minutes(block.start_time)
        block_end = time_to_minutes(block.end_time)

        # Check for overlap
        if start_mins < block_end and end_mins > block_start:
            return True

    # Check for recurring time-specific blocks on this day of week
    recurring_blocks = BlockedTime.query.filter(
        BlockedTime.is_recurring_weekly == True,
        BlockedTime.recurring_day_of_week == day_of_week,
        BlockedTime.is_all_day == False
    ).all()

    for block in recurring_blocks:
        block_start = time_to_minutes(block.start_time)
        block_end = time_to_minutes(block.end_time)

        # Check for overlap
        if start_mins < block_end and end_mins > block_start:
            return True

    return False


def check_slot_available(booking_date, start_time, end_time):
    """
    Check if a time slot is available (no overlapping bookings or blocked times).
    Returns True if available, False if there's a conflict.
    """
    start_mins = time_to_minutes(start_time)
    end_mins = time_to_minutes(end_time)

    # First check if the time is blocked
    if is_time_blocked(booking_date, start_time, end_time):
        return False

    # Get all bookings for this date
    existing_bookings = Booking.query.filter_by(
        booking_date=booking_date,
        status='confirmed'
    ).all()

    for booking in existing_bookings:
        existing_start = time_to_minutes(booking.booking_time)
        existing_end = time_to_minutes(booking.end_time)

        # Check for overlap: slots overlap if one starts before the other ends
        if start_mins < existing_end and end_mins > existing_start:
            return False

    return True


def is_day_fully_blocked(booking_date):
    """Check if an entire day is blocked (all-day block exists)."""
    day_of_week = booking_date.weekday()

    # Check for all-day block on this specific date
    all_day_block = BlockedTime.query.filter_by(
        date=booking_date,
        is_all_day=True,
        is_recurring_weekly=False
    ).first()

    if all_day_block:
        return True

    # Check for recurring all-day block on this day of week
    recurring_all_day = BlockedTime.query.filter_by(
        is_recurring_weekly=True,
        recurring_day_of_week=day_of_week,
        is_all_day=True
    ).first()

    if recurring_all_day:
        return True

    return False


def get_available_slots_for_date(service, booking_date_obj):
    """
    Generate available time slots for a given service and date.
    Uses 30-minute intervals, accounts for service duration, and checks for conflicts.
    """
    # First check if the entire day is blocked
    if is_day_fully_blocked(booking_date_obj):
        return []

    day_of_week = booking_date_obj.weekday()

    # Get availability for this day
    availability = Availability.query.filter_by(
        day_of_week=day_of_week,
        is_active=True
    ).all()

    if not availability:
        return []

    slots = []
    service_duration = service.duration_minutes

    for avail in availability:
        start_mins = time_to_minutes(avail.start_time)
        end_mins = time_to_minutes(avail.end_time)

        # Generate slots at 30-minute intervals
        current = start_mins
        while current + service_duration <= end_mins:
            slot_start = minutes_to_time(current)
            slot_end = minutes_to_time(current + service_duration)

            # Check if this slot is available (no conflicts with bookings or blocked times)
            if check_slot_available(booking_date_obj, slot_start, slot_end):
                slots.append({
                    'start': slot_start,
                    'end': slot_end
                })

            current += 30  # 30-minute intervals

    return slots


def get_available_slots_for_duration(duration_minutes, booking_date_obj):
    """
    Generate available time slots for a given duration and date.
    Used for multi-service bookings where we need to calculate based on total duration.
    """
    # First check if the entire day is blocked
    if is_day_fully_blocked(booking_date_obj):
        return []

    day_of_week = booking_date_obj.weekday()

    # Get availability for this day
    availability = Availability.query.filter_by(
        day_of_week=day_of_week,
        is_active=True
    ).all()

    if not availability:
        return []

    slots = []

    for avail in availability:
        start_mins = time_to_minutes(avail.start_time)
        end_mins = time_to_minutes(avail.end_time)

        # Generate slots at 30-minute intervals
        current = start_mins
        while current + duration_minutes <= end_mins:
            slot_start = minutes_to_time(current)
            slot_end = minutes_to_time(current + duration_minutes)

            # Check if this slot is available (no conflicts with bookings or blocked times)
            if check_slot_available(booking_date_obj, slot_start, slot_end):
                slots.append({
                    'start': slot_start,
                    'end': slot_end
                })

            current += 30  # 30-minute intervals

    return slots


def validate_csv_row(row, row_num, services_dict):
    """Validate a single CSV row and return errors if any"""
    errors = []

    # Check required fields
    required_fields = ['customer_name', 'customer_email', 'service_name', 'booking_date', 'booking_time']
    for field in required_fields:
        if field not in row or not row[field].strip():
            errors.append(f"Row {row_num}: Missing required field '{field}'")

    if errors:
        return errors, None

    # Validate service exists
    service_name = row['service_name'].strip()
    if service_name not in services_dict:
        errors.append(f"Row {row_num}: Service '{service_name}' not found")
        return errors, None

    service = services_dict[service_name]

    # Validate date format
    try:
        booking_date = datetime.strptime(row['booking_date'].strip(), '%Y-%m-%d').date()
    except ValueError:
        errors.append(f"Row {row_num}: Invalid date format '{row['booking_date']}'. Use YYYY-MM-DD")
        return errors, None

    # Validate time format
    time_str = row['booking_time'].strip()
    try:
        # Handle both HH:MM and H:MM formats
        if len(time_str) == 4 and ':' in time_str:
            time_str = '0' + time_str
        datetime.strptime(time_str, '%H:%M')
        booking_time = time_str
    except ValueError:
        errors.append(f"Row {row_num}: Invalid time format '{row['booking_time']}'. Use HH:MM (24-hour)")
        return errors, None

    # Calculate end time
    start_mins = time_to_minutes(booking_time)
    end_mins = start_mins + service.duration_minutes
    end_time = minutes_to_time(end_mins)

    # Check for duplicate/overlapping bookings
    if not check_slot_available(booking_date, booking_time, end_time):
        errors.append(f"Row {row_num}: Time slot {booking_time} on {booking_date} conflicts with existing booking")
        return errors, None

    # Return validated data
    return errors, {
        'customer_name': row['customer_name'].strip(),
        'customer_email': row['customer_email'].strip(),
        'customer_phone': row.get('customer_phone', '').strip(),
        'service': service,
        'booking_date': booking_date,
        'booking_time': booking_time,
        'end_time': end_time
    }


def parse_csv_file(file_content):
    """Parse CSV content and return rows"""
    # Try to detect the encoding and handle BOM
    try:
        content = file_content.decode('utf-8-sig')
    except UnicodeDecodeError:
        content = file_content.decode('latin-1')

    reader = csv.DictReader(io.StringIO(content))
    return list(reader)


@app.route('/')
def home():
    return render_template('home.html')


# ==================== ADMIN: LOGIN ====================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_calendar'))

    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        # First try database authentication
        admin_user = AdminUser.query.filter_by(username=username, is_active=True).first()

        if admin_user and admin_user.check_password(password):
            # Database user login
            session['admin_logged_in'] = True
            session['admin_user_id'] = admin_user.id
            session['admin_name'] = admin_user.name
            session['admin_role'] = admin_user.role

            # Update last login
            admin_user.last_login = datetime.utcnow()
            db.session.commit()

            # Log the activity
            ActivityLog.log(
                action_type='owner_login' if admin_user.is_owner() else 'staff_login',
                description=f'{admin_user.name} logged in',
                admin_user_id=admin_user.id
            )

            flash(f'Welcome back, {admin_user.name}!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('admin_calendar'))

        # Fallback to environment variable authentication (for initial setup / backwards compatibility)
        elif username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            session['admin_name'] = 'Owner'
            session['admin_role'] = 'owner'
            flash('Logged in successfully!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('admin_calendar'))
        else:
            flash('Invalid username or password.', 'error')

    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_user_id', None)
    session.pop('admin_name', None)
    session.pop('admin_role', None)
    flash('Logged out successfully.', 'success')
    return redirect(url_for('home'))


# ==================== ADMIN: CATEGORIES ====================

@app.route('/admin/categories')
@login_required
def admin_categories():
    categories = Category.query.filter_by(is_active=True).order_by(Category.display_order).all()
    uncategorised = Service.query.filter_by(is_active=True, category_id=None).order_by(Service.name).all()
    return render_template('admin_categories.html', categories=categories, uncategorised=uncategorised)


@app.route('/admin/categories/add', methods=['GET', 'POST'])
@login_required
def add_category():
    if request.method == 'POST':
        name = request.form['name']

        # Check if category already exists
        existing = Category.query.filter_by(name=name).first()
        if existing:
            flash('A category with this name already exists.', 'error')
            return render_template('add_category.html')

        # Get the highest display order
        max_order = db.session.query(db.func.max(Category.display_order)).scalar() or 0

        category = Category(
            name=name,
            display_order=max_order + 1
        )
        db.session.add(category)
        db.session.commit()

        flash('Category added successfully!', 'success')
        return redirect(url_for('admin_categories'))

    return render_template('add_category.html')


@app.route('/admin/categories/edit/<int:category_id>', methods=['GET', 'POST'])
@login_required
def edit_category(category_id):
    category = Category.query.get_or_404(category_id)

    if request.method == 'POST':
        category.name = request.form['name']
        db.session.commit()
        flash('Category updated successfully!', 'success')
        return redirect(url_for('admin_categories'))

    return render_template('edit_category.html', category=category)


@app.route('/admin/categories/delete/<int:category_id>', methods=['POST'])
@login_required
def delete_category(category_id):
    category = Category.query.get_or_404(category_id)

    # Move services in this category to uncategorized
    Service.query.filter_by(category_id=category_id).update({'category_id': None})

    category.is_active = False
    db.session.commit()
    flash('Category deleted. Services moved to uncategorized.', 'success')
    return redirect(url_for('admin_categories'))


@app.route('/admin/categories/reorder', methods=['POST'])
@login_required
def reorder_categories():
    """Reorder categories via AJAX"""
    order = request.json.get('order', [])
    for index, cat_id in enumerate(order):
        category = Category.query.get(cat_id)
        if category:
            category.display_order = index
    db.session.commit()
    return jsonify({'success': True})


@app.route('/admin/services/move-category', methods=['POST'])
@login_required
def move_service_to_category():
    """Move a service to a different category from the categories page"""
    service_id = request.form.get('service_id')
    category_id = request.form.get('category_id')

    service = Service.query.get_or_404(service_id)

    if category_id:
        # Moving to a category
        category = Category.query.get_or_404(category_id)
        service.category_id = category.id
        flash(f'"{service.name}" moved to {category.name}.', 'success')
    else:
        # Moving to uncategorised
        service.category_id = None
        flash(f'"{service.name}" moved to Uncategorised.', 'success')

    db.session.commit()
    return redirect(url_for('admin_categories'))


# ==================== ADMIN: SERVICES ====================

@app.route('/admin/services')
@login_required
def admin_services():
    # Get all categories with their services
    categories = Category.query.filter_by(is_active=True).order_by(Category.display_order).all()

    # Get uncategorized services
    uncategorized = Service.query.filter_by(is_active=True, category_id=None).order_by(Service.display_order).all()

    return render_template('admin_services.html', categories=categories, uncategorized=uncategorized)


@app.route('/admin/services/add', methods=['GET', 'POST'])
@login_required
def add_service():
    categories = Category.query.filter_by(is_active=True).order_by(Category.display_order).all()

    if request.method == 'POST':
        name = request.form['name']
        duration = int(request.form['duration_minutes'])
        price = float(request.form.get('price', 0) or 0)
        description = request.form.get('description', '')
        category_id = request.form.get('category_id')
        if category_id:
            category_id = int(category_id)
        else:
            category_id = None

        service = Service(
            name=name,
            duration_minutes=duration,
            price=price,
            description=description,
            category_id=category_id
        )
        db.session.add(service)
        db.session.commit()

        flash('Service added successfully!', 'success')
        return redirect(url_for('admin_services'))

    return render_template('add_service.html', categories=categories)


@app.route('/admin/services/edit/<int:service_id>', methods=['GET', 'POST'])
@login_required
def edit_service(service_id):
    service = Service.query.get_or_404(service_id)
    categories = Category.query.filter_by(is_active=True).order_by(Category.display_order).all()

    if request.method == 'POST':
        service.name = request.form['name']
        service.duration_minutes = int(request.form['duration_minutes'])
        service.price = float(request.form.get('price', 0) or 0)
        service.description = request.form.get('description', '')
        category_id = request.form.get('category_id')
        service.category_id = int(category_id) if category_id else None

        db.session.commit()
        flash('Service updated successfully!', 'success')
        return redirect(url_for('admin_services'))

    return render_template('edit_service.html', service=service, categories=categories)


@app.route('/admin/services/delete/<int:service_id>', methods=['POST'])
@login_required
def delete_service(service_id):
    service = Service.query.get_or_404(service_id)
    service.is_active = False  # Soft delete
    db.session.commit()
    flash('Service deleted successfully!', 'success')
    return redirect(url_for('admin_services'))


@app.route('/admin/services/move/<int:service_id>', methods=['POST'])
@login_required
def move_service_category(service_id):
    """Move a service to a different category"""
    service = Service.query.get_or_404(service_id)
    category_id = request.form.get('category_id')
    service.category_id = int(category_id) if category_id else None
    db.session.commit()
    flash(f'Service moved successfully!', 'success')
    return redirect(url_for('admin_services'))


@app.route('/admin/services/reorder', methods=['POST'])
@login_required
def reorder_services():
    """Reorder services within a category via AJAX"""
    order = request.json.get('order', [])
    category_id = request.json.get('category_id')  # Can be None for uncategorized

    for index, service_id in enumerate(order):
        service = Service.query.get(service_id)
        if service:
            service.display_order = index
    db.session.commit()
    return jsonify({'success': True})


# ==================== ADMIN: AVAILABILITY ====================

@app.route('/admin/availability')
@login_required
def admin_availability():
    availability = Availability.query.filter_by(is_active=True).order_by(Availability.day_of_week).all()
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    return render_template('admin_availability.html', availability=availability, days=days)


@app.route('/admin/availability/add', methods=['GET', 'POST'])
@login_required
def add_availability():
    if request.method == 'POST':
        day = int(request.form['day_of_week'])
        start = request.form['start_time']
        end = request.form['end_time']

        avail = Availability(day_of_week=day, start_time=start, end_time=end)
        db.session.add(avail)
        db.session.commit()

        flash('Availability added successfully!', 'success')
        return redirect(url_for('admin_availability'))

    return render_template('add_availability.html')


@app.route('/admin/availability/delete/<int:avail_id>', methods=['POST'])
@login_required
def delete_availability(avail_id):
    avail = Availability.query.get_or_404(avail_id)
    avail.is_active = False  # Soft delete
    db.session.commit()
    flash('Availability removed successfully!', 'success')
    return redirect(url_for('admin_availability'))


# ==================== ADMIN: BLOCKED TIMES ====================

@app.route('/admin/blocked-times')
@login_required
def admin_blocked_times():
    """View all blocked times"""
    # Get upcoming blocked times (today onwards)
    today = date.today()
    blocked_times = BlockedTime.query.filter(
        BlockedTime.date >= today
    ).order_by(BlockedTime.date, BlockedTime.start_time).all()

    # Get recurring blocks
    recurring_blocks = BlockedTime.query.filter_by(is_recurring_weekly=True).all()

    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    return render_template('admin_blocked_times.html',
                         blocked_times=blocked_times,
                         recurring_blocks=recurring_blocks,
                         days=days,
                         today=today.isoformat())


@app.route('/admin/blocked-times/add', methods=['GET', 'POST'])
@login_required
def add_blocked_time():
    """Add a new blocked time"""
    if request.method == 'POST':
        block_type = request.form.get('block_type', 'single')
        reason = request.form.get('reason', '')
        is_all_day = request.form.get('is_all_day') == 'yes'

        if block_type == 'recurring':
            # Recurring weekly block (e.g., lunch every day)
            day_of_week = int(request.form['day_of_week'])
            start_time = None if is_all_day else request.form.get('start_time')
            end_time = None if is_all_day else request.form.get('end_time')

            blocked = BlockedTime(
                date=date.today(),  # Placeholder date for recurring
                start_time=start_time,
                end_time=end_time,
                reason=reason,
                is_all_day=is_all_day,
                is_recurring_weekly=True,
                recurring_day_of_week=day_of_week
            )
            db.session.add(blocked)
            db.session.commit()
            flash('Recurring blocked time added successfully!', 'success')

        elif block_type == 'range':
            # Block a date range (e.g., holiday)
            start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()

            # Create a blocked time for each day in the range
            current_date = start_date
            count = 0
            while current_date <= end_date:
                blocked = BlockedTime(
                    date=current_date,
                    start_time=None,
                    end_time=None,
                    reason=reason,
                    is_all_day=True,
                    is_recurring_weekly=False
                )
                db.session.add(blocked)
                current_date += timedelta(days=1)
                count += 1

            db.session.commit()
            flash(f'Blocked {count} days successfully!', 'success')

        else:
            # Single day/time block
            block_date = datetime.strptime(request.form['block_date'], '%Y-%m-%d').date()
            start_time = None if is_all_day else request.form.get('start_time')
            end_time = None if is_all_day else request.form.get('end_time')

            blocked = BlockedTime(
                date=block_date,
                start_time=start_time,
                end_time=end_time,
                reason=reason,
                is_all_day=is_all_day,
                is_recurring_weekly=False
            )
            db.session.add(blocked)
            db.session.commit()
            flash('Blocked time added successfully!', 'success')

        return redirect(url_for('admin_blocked_times'))

    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    today = date.today().isoformat()
    max_date = (date.today() + timedelta(days=365)).isoformat()
    return render_template('add_blocked_time.html', days=days, today=today, max_date=max_date)


@app.route('/admin/blocked-times/delete/<int:block_id>', methods=['POST'])
@login_required
def delete_blocked_time(block_id):
    """Delete a blocked time"""
    blocked = BlockedTime.query.get_or_404(block_id)
    db.session.delete(blocked)
    db.session.commit()
    flash('Blocked time removed successfully!', 'success')
    return redirect(url_for('admin_blocked_times'))


@app.route('/admin/blocked-times/add-quick', methods=['POST'])
@login_required
def add_quick_blocked_time():
    """Quick add blocked time from calendar"""
    block_date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
    start_time = request.form['start_time']
    duration = request.form['duration']
    reason = request.form.get('reason', '')
    redirect_to = request.form.get('redirect', 'calendar')

    if duration == 'all_day':
        # Block rest of day
        blocked = BlockedTime(
            date=block_date,
            start_time=start_time,
            end_time='23:59',
            reason=reason or 'Blocked',
            is_all_day=False
        )
    else:
        # Calculate end time based on duration
        start_parts = start_time.split(':')
        start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
        end_minutes = start_minutes + int(duration)
        end_hour = end_minutes // 60
        end_minute = end_minutes % 60
        end_time = f"{end_hour:02d}:{end_minute:02d}"

        blocked = BlockedTime(
            date=block_date,
            start_time=start_time,
            end_time=end_time,
            reason=reason or 'Blocked',
            is_all_day=False
        )

    db.session.add(blocked)
    db.session.commit()
    flash('Time blocked successfully!', 'success')

    if redirect_to == 'calendar':
        return redirect(url_for('admin_calendar', view='day', date=block_date.isoformat()))
    return redirect(url_for('admin_blocked_times'))


# ==================== ADMIN: CALENDAR ====================

@app.route('/admin/calendar')
@login_required
def admin_calendar():
    """Calendar view showing bookings and blocked times"""
    # Auto-complete past appointments first
    auto_complete_past_appointments()

    view = request.args.get('view', 'week')  # 'day', 'week' or 'month'
    date_str = request.args.get('date')

    # Get all emails/phones that have notes (for showing indicators on calendar)
    emails_with_notes = set()
    phones_with_notes = set()
    # Check ClientNote table
    for note in ClientNote.query.all():
        if note.client_email:
            emails_with_notes.add(note.client_email.lower())
    # Check Client.notes field
    for client in Client.query.all():
        if client.notes and client.notes.strip():
            if client.email:
                emails_with_notes.add(client.email.lower())
            if client.phone:
                phones_with_notes.add(client.phone)

    if date_str:
        current_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        current_date = date.today()

    days_of_week = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    # Day view - show time slots for a single day
    if view == 'day':
        prev_date = current_date - timedelta(days=1)
        next_date = current_date + timedelta(days=1)
        title = current_date.strftime('%A, %d %B %Y')

        # Get availability for this day of week
        day_of_week = current_date.weekday()
        availability = Availability.query.filter_by(day_of_week=day_of_week, is_active=True).first()

        # For admin day view, always show full day 9am-9pm for full visibility
        # Admin needs to see all times, even outside normal operating hours
        start_hour = 9
        end_hour = 21  # Show until 9pm
        # Extend end time if availability goes later than 9pm
        if availability:
            avail_end = int(availability.end_time.split(':')[0])
            end_hour = max(avail_end + 1, end_hour)

        # Generate time slots (every 15 minutes)
        time_slots = []
        for hour in range(start_hour, end_hour):
            for minute in [0, 15, 30, 45]:
                slot_time = f"{hour:02d}:{minute:02d}"
                time_slots.append({
                    'time': slot_time,
                    'booking': None,
                    'blocked': None
                })

        # Get bookings for this day
        day_bookings = Booking.query.filter(
            Booking.booking_date == current_date,
            Booking.status.in_(['confirmed', 'no_show', 'completed'])
        ).order_by(Booking.booking_time).all()

        # Get blocked times for this day
        day_blocks = BlockedTime.query.filter_by(
            date=current_date,
            is_recurring_weekly=False
        ).all()

        # Get recurring blocks
        recurring_blocks = BlockedTime.query.filter_by(
            is_recurring_weekly=True,
            recurring_day_of_week=day_of_week
        ).all()

        all_blocks = day_blocks + recurring_blocks

        # Check if day is fully blocked
        is_fully_blocked = any(b.is_all_day for b in all_blocks)

        # Map bookings and blocks to time slots
        for slot in time_slots:
            slot_time = slot['time']

            # Check for bookings that cover this slot
            for booking in day_bookings:
                if booking.booking_time <= slot_time < booking.end_time:
                    # Create CSS-safe category slug
                    if booking.service.category:
                        cat_name = booking.service.category.name.lower()
                        if 'ear' in cat_name:
                            category_slug = 'ears'
                        elif 'nose' in cat_name or 'nostril' in cat_name:
                            category_slug = 'nose'
                        elif 'consult' in cat_name:
                            category_slug = 'consultation'
                        elif 'jewel' in cat_name:
                            category_slug = 'service'
                        elif 'under' in cat_name or '16' in cat_name:
                            category_slug = 'under16'
                        elif 'body' in cat_name:
                            category_slug = 'body'
                        elif 'lip' in cat_name:
                            category_slug = 'lips'
                        elif 'face' in cat_name or 'facial' in cat_name:
                            category_slug = 'face'
                        else:
                            category_slug = 'other'
                    else:
                        category_slug = 'other'
                    has_notes = False
                    if booking.customer_email and booking.customer_email.lower() in emails_with_notes:
                        has_notes = True
                    elif booking.customer_phone and booking.customer_phone in phones_with_notes:
                        has_notes = True
                    slot['booking'] = {
                        'id': booking.id,
                        'time': booking.booking_time,
                        'end_time': booking.end_time,
                        'customer': booking.customer_name,
                        'email': booking.customer_email,
                        'service': booking.service.name,
                        'status': booking.status,
                        'category': category_slug,
                        'has_notes': has_notes
                    }
                    break

            # Check for blocks that cover this slot
            if not slot['booking']:
                for block in all_blocks:
                    if block.is_all_day:
                        slot['blocked'] = {
                            'reason': block.reason,
                            'is_all_day': True,
                            'is_recurring': block.is_recurring_weekly,
                            'start_time': 'All',
                            'end_time': 'Day'
                        }
                        break
                    elif block.start_time and block.end_time:
                        if block.start_time <= slot_time < block.end_time:
                            slot['blocked'] = {
                                'reason': block.reason,
                                'is_all_day': False,
                                'is_recurring': block.is_recurring_weekly,
                                'start_time': block.start_time,
                                'end_time': block.end_time
                            }
                            break

        day_data = {
            'is_fully_blocked': is_fully_blocked
        }

        return render_template('admin_calendar.html',
                             view=view,
                             current_date=current_date,
                             prev_date=prev_date.isoformat(),
                             next_date=next_date.isoformat(),
                             title=title,
                             days_of_week=days_of_week,
                             today=date.today(),
                             time_slots=time_slots,
                             day_data=day_data)

    # Month view
    elif view == 'month':
        # Get the first day of the month
        first_of_month = current_date.replace(day=1)
        # Get the last day of the month
        if current_date.month == 12:
            last_of_month = current_date.replace(day=31)
        else:
            last_of_month = (first_of_month.replace(month=first_of_month.month + 1) - timedelta(days=1))

        # Get the Monday of the week containing the first of the month
        start_date = first_of_month - timedelta(days=first_of_month.weekday())
        # Get the Sunday of the week containing the last of the month
        end_date = last_of_month + timedelta(days=(6 - last_of_month.weekday()))

        # Navigation dates
        prev_date = (first_of_month - timedelta(days=1)).replace(day=1)
        next_date = (last_of_month + timedelta(days=1))

        title = current_date.strftime('%B %Y')
    else:
        # Week view - get Monday of current week
        start_date = current_date - timedelta(days=current_date.weekday())
        end_date = start_date + timedelta(days=6)

        # Navigation dates
        prev_date = start_date - timedelta(days=7)
        next_date = start_date + timedelta(days=7)

        title = f"{start_date.strftime('%d %b')} - {end_date.strftime('%d %b %Y')}"

    # Determine working hours for week view
    start_hour = 9  # Default start
    end_hour = 21   # Default end (9pm)

    # Try to get availability to determine hours
    all_availabilities = Availability.query.filter_by(is_active=True).all()
    if all_availabilities:
        earliest = min(int(a.start_time.split(':')[0]) for a in all_availabilities)
        latest = max(int(a.end_time.split(':')[0]) for a in all_availabilities)
        start_hour = earliest
        end_hour = max(latest + 1, 21)  # Include last hour, minimum 9pm

    hours = list(range(start_hour, end_hour))

    # Build calendar data for week/month views
    calendar_data = []
    week_days = []  # For visual week view
    current = start_date

    while current <= end_date:
        day_name_full = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][current.weekday()]
        day_data = {
            'date': current,
            'day_name': day_name_full,
            'is_today': current == date.today(),
            'is_current_month': current.month == current_date.month,
            'bookings': [],
            'blocked_times': [],
            'is_fully_blocked': False
        }

        # Get bookings for this day (confirmed and no-show, exclude cancelled)
        day_bookings = Booking.query.filter(
            Booking.booking_date == current,
            Booking.status.in_(['confirmed', 'no_show', 'completed'])
        ).order_by(Booking.booking_time).all()

        for booking in day_bookings:
            # Create CSS-safe category slug from category name
            if booking.service.category:
                cat_name = booking.service.category.name.lower()
                # Map common category names to color slugs
                if 'ear' in cat_name:
                    category_slug = 'ears'
                elif 'nose' in cat_name or 'nostril' in cat_name:
                    category_slug = 'nose'
                elif 'consult' in cat_name:
                    category_slug = 'consultation'
                elif 'jewel' in cat_name:
                    category_slug = 'service'
                elif 'under' in cat_name or '16' in cat_name:
                    category_slug = 'under16'
                elif 'body' in cat_name:
                    category_slug = 'body'
                elif 'lip' in cat_name:
                    category_slug = 'lips'
                elif 'face' in cat_name or 'facial' in cat_name:
                    category_slug = 'face'
                else:
                    category_slug = 'other'
            else:
                category_slug = 'other'
            has_notes = False
            if booking.customer_email and booking.customer_email.lower() in emails_with_notes:
                has_notes = True
            elif booking.customer_phone and booking.customer_phone in phones_with_notes:
                has_notes = True
            day_data['bookings'].append({
                'id': booking.id,
                'time': booking.booking_time,
                'end_time': booking.end_time,
                'customer': booking.customer_name,
                'email': booking.customer_email,
                'service': booking.service.name,
                'service_id': booking.service_id,
                'status': booking.status,
                'category': category_slug,
                'has_notes': has_notes,
                'price': booking.service.price if booking.service else 0
            })

        # Get blocked times for this day
        day_blocks = BlockedTime.query.filter_by(
            date=current,
            is_recurring_weekly=False
        ).order_by(BlockedTime.start_time).all()

        for block in day_blocks:
            if block.is_all_day:
                day_data['is_fully_blocked'] = True
            day_data['blocked_times'].append({
                'id': block.id,
                'start_time': block.start_time,
                'end_time': block.end_time,
                'reason': block.reason,
                'is_all_day': block.is_all_day
            })

        # Check for recurring blocks
        day_of_week = current.weekday()
        recurring_blocks = BlockedTime.query.filter_by(
            is_recurring_weekly=True,
            recurring_day_of_week=day_of_week
        ).all()

        for block in recurring_blocks:
            if block.is_all_day:
                day_data['is_fully_blocked'] = True
            day_data['blocked_times'].append({
                'id': block.id,
                'start_time': block.start_time,
                'end_time': block.end_time,
                'reason': block.reason,
                'is_all_day': block.is_all_day,
                'is_recurring': True
            })

        calendar_data.append(day_data)
        if view == 'week':
            week_days.append(day_data)
        current += timedelta(days=1)

    return render_template('admin_calendar.html',
                         calendar_data=calendar_data,
                         week_days=week_days,
                         hours=hours,
                         start_hour=start_hour,
                         view=view,
                         current_date=current_date,
                         prev_date=prev_date.isoformat(),
                         next_date=next_date.isoformat(),
                         title=title,
                         days_of_week=days_of_week,
                         today=date.today())


# ==================== ADMIN: BOOKINGS ====================

@app.route('/admin/bookings')
@login_required
def admin_bookings():
    # Auto-complete past appointments first
    auto_complete_past_appointments()

    bookings = Booking.query.order_by(Booking.booking_date.desc(), Booking.booking_time.desc()).all()
    return render_template('admin_bookings.html', bookings=bookings)


@app.route('/admin/booking/add', methods=['GET', 'POST'])
@login_required
def add_booking():
    """Add a booking manually from the calendar"""
    if request.method == 'POST':
        service_id = int(request.form['service_id'])
        service = Service.query.get_or_404(service_id)

        booking_date = datetime.strptime(request.form['booking_date'], '%Y-%m-%d').date()
        booking_time = request.form['booking_time']

        # Calculate end time based on service duration
        start_parts = booking_time.split(':')
        start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
        end_minutes = start_minutes + service.duration_minutes
        end_hour = end_minutes // 60
        end_minute = end_minutes % 60
        end_time = f"{end_hour:02d}:{end_minute:02d}"

        booking = Booking(
            service_id=service_id,
            customer_name=request.form['customer_name'],
            customer_email=request.form['customer_email'],
            customer_phone=request.form.get('customer_phone', ''),
            booking_date=booking_date,
            booking_time=booking_time,
            end_time=end_time,
            status='confirmed',
            notes=request.form.get('notes', '')
        )

        db.session.add(booking)
        db.session.commit()

        # Log the activity
        admin_name = session.get('admin_name', 'Admin')
        ActivityLog.log(
            action_type='booking_created',
            description=f'{admin_name} created booking for {booking.customer_name} ({service.name} on {booking_date.strftime("%d %b")} at {booking_time})',
            admin_user_id=session.get('admin_user_id'),
            booking_id=booking.id,
            client_email=booking.customer_email
        )

        flash('Booking added successfully!', 'success')
        return redirect(url_for('admin_calendar', view='day', date=booking_date.isoformat()))

    # GET request - show form
    booking_date = request.args.get('date', date.today().isoformat())
    booking_time = request.args.get('time', '09:00')
    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()

    # Group services by category
    categories = Category.query.filter_by(is_active=True).order_by(Category.display_order).all()

    return render_template('add_booking.html',
                         booking_date=booking_date,
                         booking_time=booking_time,
                         services=services,
                         categories=categories)


@app.route('/admin/bookings/cancel/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = 'cancelled'
    db.session.commit()

    # Log the activity
    admin_name = session.get('admin_name', 'Admin')
    ActivityLog.log(
        action_type='booking_cancelled',
        description=f'{admin_name} cancelled booking for {booking.customer_name} ({booking.service.name} on {booking.booking_date.strftime("%d %b")} at {booking.booking_time})',
        admin_user_id=session.get('admin_user_id'),
        booking_id=booking.id,
        client_email=booking.customer_email
    )

    print("\n" + "=" * 50)
    print("BOOKING CANCELLED")
    print("=" * 50)
    print(f"Booking ID: {booking.id}")
    print(f"Customer: {booking.customer_name}")
    print(f"Date: {booking.booking_date}")
    print(f"Time: {booking.booking_time}")
    print("=" * 50 + "\n")

    flash('Booking cancelled successfully!', 'success')

    # Redirect back to calendar if came from there
    if request.referrer and 'calendar' in request.referrer:
        return redirect(request.referrer)
    return redirect(url_for('admin_bookings'))


@app.route('/admin/bookings/no-show/<int:booking_id>', methods=['POST'])
@login_required
def mark_no_show(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = 'no_show'
    booking.no_show_at = datetime.now()
    db.session.commit()

    # Log the activity
    admin_name = session.get('admin_name', 'Admin')
    ActivityLog.log(
        action_type='booking_no_show',
        description=f'{admin_name} marked {booking.customer_name} as no-show ({booking.service.name} on {booking.booking_date.strftime("%d %b")})',
        admin_user_id=session.get('admin_user_id'),
        booking_id=booking.id,
        client_email=booking.customer_email
    )

    print("\n" + "=" * 50)
    print("BOOKING MARKED AS NO-SHOW")
    print("=" * 50)
    print(f"Booking ID: {booking.id}")
    print(f"Customer: {booking.customer_name}")
    print(f"Date: {booking.booking_date}")
    print(f"Time: {booking.booking_time}")
    print("=" * 50 + "\n")

    flash('Booking marked as no-show.', 'warning')

    # Redirect back to calendar if came from there
    if request.referrer and 'calendar' in request.referrer:
        return redirect(request.referrer)
    return redirect(url_for('admin_bookings'))


@app.route('/admin/bookings/undo-no-show/<int:booking_id>', methods=['POST'])
@login_required
def undo_no_show(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = 'confirmed'
    booking.no_show_at = None
    db.session.commit()

    flash('No-show status removed. Booking is now confirmed.', 'success')

    # Redirect back to calendar if came from there
    if request.referrer and 'calendar' in request.referrer:
        return redirect(request.referrer)
    return redirect(url_for('admin_bookings'))


@app.route('/admin/bookings/complete/<int:booking_id>', methods=['POST'])
@login_required
def mark_complete(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = 'completed'
    db.session.commit()

    # Log the activity
    admin_name = session.get('admin_name', 'Admin')
    ActivityLog.log(
        action_type='booking_completed',
        description=f'{admin_name} completed booking for {booking.customer_name} ({booking.service.name})',
        admin_user_id=session.get('admin_user_id'),
        booking_id=booking.id,
        client_email=booking.customer_email
    )

    flash('Booking marked as completed.', 'success')

    # Redirect back to calendar if came from there
    if request.referrer and 'calendar' in request.referrer:
        return redirect(request.referrer)
    return redirect(url_for('admin_bookings'))


@app.route('/admin/booking/extend/<int:booking_id>', methods=['POST'])
@login_required
def extend_booking(booking_id):
    """Extend or reduce a booking duration by specified minutes"""
    booking = Booking.query.get_or_404(booking_id)

    extend_minutes = int(request.form.get('extend_minutes', 0))

    if extend_minutes == 0:
        flash('Invalid extension time.', 'error')
        return redirect(url_for('move_booking', booking_id=booking_id))

    # Calculate current duration
    current_start_mins = time_to_minutes(booking.booking_time)
    current_end_mins = time_to_minutes(booking.end_time)
    current_duration = current_end_mins - current_start_mins

    # Calculate new duration
    new_duration = current_duration + extend_minutes

    # Minimum duration is 15 minutes
    if new_duration < 15:
        flash('Appointment duration cannot be less than 15 minutes.', 'error')
        return redirect(url_for('move_booking', booking_id=booking_id))

    # Maximum duration is 4 hours (240 minutes)
    if new_duration > 240:
        flash('Appointment duration cannot exceed 4 hours.', 'error')
        return redirect(url_for('move_booking', booking_id=booking_id))

    # Calculate new end time
    new_end_mins = current_start_mins + new_duration
    new_end_time = minutes_to_time(new_end_mins)

    # Check for conflicts with other bookings (only if extending)
    if extend_minutes > 0:
        existing_booking = Booking.query.filter(
            Booking.id != booking.id,
            Booking.booking_date == booking.booking_date,
            Booking.status.in_(['confirmed', 'completed']),
            Booking.booking_time < new_end_time,
            Booking.end_time > booking.end_time
        ).first()

        if existing_booking:
            flash(f'Cannot extend - conflicts with booking at {existing_booking.booking_time}.', 'error')
            return redirect(url_for('move_booking', booking_id=booking_id))

        # Check for blocked times
        if is_time_blocked(booking.booking_date, booking.end_time, new_end_time):
            flash('Cannot extend - the time is blocked.', 'error')
            return redirect(url_for('move_booking', booking_id=booking_id))

    # Update the booking
    old_end_time = booking.end_time
    booking.end_time = new_end_time
    db.session.commit()

    action = "Extended" if extend_minutes > 0 else "Reduced"
    print(f"\n[BOOKING {action.upper()}] #{booking.id}: {booking.customer_name}")
    print(f"  Duration changed by {extend_minutes} minutes")
    print(f"  New end time: {new_end_time} (was {old_end_time})")

    flash(f'Appointment {action.lower()} by {abs(extend_minutes)} minutes. New end time: {new_end_time}', 'success')
    return redirect(url_for('move_booking', booking_id=booking_id))


@app.route('/admin/booking/move/<int:booking_id>', methods=['GET', 'POST'])
@login_required
def move_booking(booking_id):
    """Move/reschedule a booking to a new date and time"""
    booking = Booking.query.get_or_404(booking_id)

    if request.method == 'POST':
        new_date_str = request.form.get('new_date')
        new_time = request.form.get('new_time')

        if not new_date_str or not new_time:
            flash('Please select a new date and time.', 'error')
            return redirect(url_for('move_booking', booking_id=booking_id))

        new_date = datetime.strptime(new_date_str, '%Y-%m-%d').date()

        # Calculate new end time based on service duration
        service = Service.query.get(booking.service_id)
        duration = service.duration_minutes if service else 30
        start_mins = time_to_minutes(new_time)
        end_mins = start_mins + duration
        new_end_time = minutes_to_time(end_mins)

        # Check for conflicts
        existing_booking = Booking.query.filter(
            Booking.id != booking.id,
            Booking.booking_date == new_date,
            Booking.status.in_(['confirmed', 'completed']),
            ((Booking.booking_time <= new_time) & (Booking.end_time > new_time)) |
            ((Booking.booking_time < new_end_time) & (Booking.end_time >= new_end_time)) |
            ((Booking.booking_time >= new_time) & (Booking.end_time <= new_end_time))
        ).first()

        if existing_booking:
            flash('This time slot conflicts with another booking. Please choose a different time.', 'error')
            return redirect(url_for('move_booking', booking_id=booking_id))

        # Check for blocked times
        if is_time_blocked(new_date, new_time, new_end_time):
            flash('This time slot is blocked. Please choose a different time.', 'error')
            return redirect(url_for('move_booking', booking_id=booking_id))

        # Store old details for logging
        old_date = booking.booking_date
        old_time = booking.booking_time

        # Update booking
        booking.booking_date = new_date
        booking.booking_time = new_time
        booking.end_time = new_end_time
        db.session.commit()

        print("\n" + "=" * 50)
        print("BOOKING MOVED/RESCHEDULED")
        print("=" * 50)
        print(f"Booking ID: {booking.id}")
        print(f"Customer: {booking.customer_name}")
        print(f"Service: {service.name if service else 'Unknown'}")
        print(f"From: {old_date} at {old_time}")
        print(f"To: {new_date} at {new_time}")
        print("=" * 50 + "\n")

        flash(f'Booking moved to {new_date.strftime("%A, %d %B %Y")} at {new_time}', 'success')
        return redirect(url_for('admin_calendar', view='day', date=new_date.isoformat()))

    # GET request - show the move form
    service = Service.query.get(booking.service_id)
    return render_template('move_booking.html',
                         booking=booking,
                         service=service,
                         today=date.today())


@app.route('/admin/booking/available-slots')
@login_required
def get_available_slots_for_move():
    """API endpoint to get available time slots for rescheduling a booking"""
    date_str = request.args.get('date')
    duration = request.args.get('duration', 30, type=int)
    exclude_booking_id = request.args.get('exclude_booking', type=int)

    print(f"[AVAILABLE-SLOTS] Request: date={date_str}, duration={duration}, exclude={exclude_booking_id}")

    if not date_str:
        print("[AVAILABLE-SLOTS] Error: No date provided")
        return jsonify({'error': 'Date required', 'slots': []})

    try:
        booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format', 'slots': []})

    # Check if the entire day is blocked
    if is_day_fully_blocked(booking_date):
        print(f"[AVAILABLE-SLOTS] Day {booking_date} is fully blocked")
        return jsonify({'slots': [], 'message': 'Day is fully blocked'})

    day_of_week = booking_date.weekday()
    print(f"[AVAILABLE-SLOTS] Day of week: {day_of_week} ({['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][day_of_week]})")

    # Get availability for this day
    availability = Availability.query.filter_by(
        day_of_week=day_of_week,
        is_active=True
    ).all()

    print(f"[AVAILABLE-SLOTS] Found {len(availability)} availability records for this day")

    if not availability:
        print(f"[AVAILABLE-SLOTS] No availability for day {day_of_week}")
        return jsonify({'slots': [], 'message': 'No availability set for this day'})

    slots = []

    for avail in availability:
        start_mins = time_to_minutes(avail.start_time)
        end_mins = time_to_minutes(avail.end_time)

        # Generate slots at 30-minute intervals
        current = start_mins
        while current + duration <= end_mins:
            slot_start = minutes_to_time(current)
            slot_end = minutes_to_time(current + duration)

            # Check if this slot is blocked
            if is_time_blocked(booking_date, slot_start, slot_end):
                current += 30
                continue

            # Check for conflicting bookings (excluding the one being moved)
            query = Booking.query.filter(
                Booking.booking_date == booking_date,
                Booking.status.in_(['confirmed', 'completed'])
            )
            if exclude_booking_id:
                query = query.filter(Booking.id != exclude_booking_id)
            conflict = query.all()

            slot_available = True
            slot_start_mins = time_to_minutes(slot_start)
            slot_end_mins = time_to_minutes(slot_end)

            for booking in conflict:
                existing_start = time_to_minutes(booking.booking_time)
                existing_end = time_to_minutes(booking.end_time)

                # Check for overlap
                if slot_start_mins < existing_end and slot_end_mins > existing_start:
                    slot_available = False
                    break

            if slot_available:
                slots.append({
                    'start': slot_start,
                    'end': slot_end
                })

            current += 30

    print(f"[AVAILABLE-SLOTS] Returning {len(slots)} slots")
    return jsonify({'slots': slots})


# ==================== ADMIN: CSV IMPORT ====================

@app.route('/admin/import', methods=['GET'])
@login_required
def admin_import():
    services = Service.query.filter_by(is_active=True).all()
    return render_template('admin_import.html', services=services)


@app.route('/admin/import/preview', methods=['POST'])
@login_required
def import_preview():
    if 'csv_file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('admin_import'))

    file = request.files['csv_file']

    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('admin_import'))

    if not file.filename.endswith('.csv'):
        flash('Please upload a CSV file', 'error')
        return redirect(url_for('admin_import'))

    try:
        file_content = file.read()
        rows = parse_csv_file(file_content)

        if not rows:
            flash('CSV file is empty or has no data rows', 'error')
            return redirect(url_for('admin_import'))

        # Build services dictionary for validation
        services = Service.query.filter_by(is_active=True).all()
        services_dict = {s.name: s for s in services}

        # Validate all rows
        preview_data = []
        all_errors = []
        valid_count = 0

        for i, row in enumerate(rows, start=2):  # Start at 2 (row 1 is header)
            errors, validated = validate_csv_row(row, i, services_dict)

            if errors:
                all_errors.extend(errors)
                preview_data.append({
                    'row_num': i,
                    'data': row,
                    'valid': False,
                    'errors': errors
                })
            else:
                valid_count += 1
                preview_data.append({
                    'row_num': i,
                    'data': row,
                    'valid': True,
                    'validated': validated
                })

        # Store file content in session for later import
        session['import_file_content'] = file_content.decode('utf-8-sig', errors='replace')

        return render_template('admin_import.html',
                             services=services,
                             preview_data=preview_data,
                             valid_count=valid_count,
                             error_count=len(rows) - valid_count,
                             total_count=len(rows),
                             show_preview=True)

    except Exception as e:
        flash(f'Error reading CSV file: {str(e)}', 'error')
        return redirect(url_for('admin_import'))


@app.route('/admin/import/confirm', methods=['POST'])
@login_required
def import_confirm():
    file_content = session.get('import_file_content')

    if not file_content:
        flash('No file to import. Please upload a CSV file first.', 'error')
        return redirect(url_for('admin_import'))

    try:
        rows = parse_csv_file(file_content.encode('utf-8'))

        # Build services dictionary
        services = Service.query.filter_by(is_active=True).all()
        services_dict = {s.name: s for s in services}

        # Import valid rows
        imported_count = 0
        errors = []

        for i, row in enumerate(rows, start=2):
            row_errors, validated = validate_csv_row(row, i, services_dict)

            if row_errors:
                errors.extend(row_errors)
                continue

            # Create booking
            booking = Booking(
                service_id=validated['service'].id,
                customer_name=validated['customer_name'],
                customer_email=validated['customer_email'],
                customer_phone=validated['customer_phone'],
                booking_date=validated['booking_date'],
                booking_time=validated['booking_time'],
                end_time=validated['end_time'],
                status='confirmed'
            )

            db.session.add(booking)
            imported_count += 1

            # Print notification
            print(f"\n[IMPORTED] Booking: {validated['customer_name']} - {validated['booking_date']} {validated['booking_time']}")

        db.session.commit()

        # Clear session data
        session.pop('import_file_content', None)

        # Show results
        services = Service.query.filter_by(is_active=True).all()
        return render_template('admin_import.html',
                             services=services,
                             import_complete=True,
                             imported_count=imported_count,
                             error_count=len(errors),
                             import_errors=errors)

    except Exception as e:
        db.session.rollback()
        flash(f'Error importing bookings: {str(e)}', 'error')
        return redirect(url_for('admin_import'))


@app.route('/admin/import/sample.csv')
@login_required
def download_sample_csv():
    # Get service names for sample
    services = Service.query.filter_by(is_active=True).all()
    service_name = services[0].name if services else 'Consultation'

    # Create sample CSV content
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow(['customer_name', 'customer_email', 'customer_phone', 'service_name', 'booking_date', 'booking_time'])

    # Sample data rows
    tomorrow = (date.today() + timedelta(days=1)).strftime('%Y-%m-%d')
    day_after = (date.today() + timedelta(days=2)).strftime('%Y-%m-%d')

    writer.writerow(['John Smith', 'john@example.com', '555-123-4567', service_name, tomorrow, '09:00'])
    writer.writerow(['Jane Doe', 'jane@example.com', '555-987-6543', service_name, tomorrow, '10:30'])
    writer.writerow(['Bob Wilson', 'bob@example.com', '', service_name, day_after, '14:00'])

    output.seek(0)

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=sample_bookings.csv'}
    )


# ==================== ADMIN: CLIENTS ====================

def normalize_phone(phone):
    """Normalize phone number for comparison (remove spaces, dashes, etc.)"""
    if not phone:
        return None
    # Keep only digits
    normalized = ''.join(c for c in phone if c.isdigit())
    # Return None if too short to be valid
    return normalized if len(normalized) >= 7 else None


def group_clients_by_email_or_phone(bookings):
    """
    Group bookings into client records by matching email OR phone.
    If either matches, the bookings belong to the same client.
    """
    # Maps to track which client group each email/phone belongs to
    email_to_group = {}
    phone_to_group = {}
    groups = {}  # group_id -> list of bookings
    next_group_id = 0

    for booking in bookings:
        email = booking.customer_email.lower().strip() if booking.customer_email else None
        phone = normalize_phone(booking.customer_phone)

        # Find existing group for this email or phone
        group_id = None

        if email and email in email_to_group:
            group_id = email_to_group[email]
        if phone and phone in phone_to_group:
            found_group = phone_to_group[phone]
            if group_id is None:
                group_id = found_group
            elif group_id != found_group:
                # Merge the two groups - phone matches a different group than email
                # Move all bookings from found_group to group_id
                groups[group_id].extend(groups[found_group])
                # Update all email/phone mappings that pointed to found_group
                for e, g in list(email_to_group.items()):
                    if g == found_group:
                        email_to_group[e] = group_id
                for p, g in list(phone_to_group.items()):
                    if g == found_group:
                        phone_to_group[p] = group_id
                del groups[found_group]

        # Create new group if needed
        if group_id is None:
            group_id = next_group_id
            next_group_id += 1
            groups[group_id] = []

        # Add booking to group
        groups[group_id].append(booking)

        # Update mappings
        if email:
            email_to_group[email] = group_id
        if phone:
            phone_to_group[phone] = group_id

    return groups


@app.route('/admin/clients/send-followup/<path:client_email>', methods=['POST'])
@login_required
def send_manual_followup(client_email):
    """Manually send a 6-week follow-up email to a client"""
    from email_service import send_followup_email

    # Find the most recent completed booking for this client
    booking = Booking.query.filter(
        Booking.customer_email.ilike(client_email),
        Booking.status == 'completed'
    ).order_by(Booking.booking_date.desc()).first()

    if not booking:
        # If no completed booking, try to find any booking to get client name
        booking = Booking.query.filter(
            Booking.customer_email.ilike(client_email)
        ).order_by(Booking.booking_date.desc()).first()

        if not booking:
            flash('No bookings found for this client.', 'error')
            return redirect(url_for('admin_clients'))

    # Send the follow-up email
    success = send_followup_email(booking)

    if success:
        flash(f'6-week follow-up email sent to {client_email}', 'success')
    else:
        flash('Failed to send email. Please check email settings.', 'error')

    return redirect(url_for('client_profile', identifier=client_email))


@app.route('/admin/booking/toggle-day-after-block/<int:booking_id>', methods=['POST'])
@login_required
def toggle_day_after_block(booking_id):
    """Toggle whether a booking should receive the 24-hour follow-up email"""
    booking = Booking.query.get_or_404(booking_id)

    # Toggle the block status
    booking.day_after_blocked = not booking.day_after_blocked
    db.session.commit()

    if booking.day_after_blocked:
        flash(f'24-hour email blocked for this appointment', 'success')
    else:
        flash(f'24-hour email enabled for this appointment', 'success')

    # Return to the calendar
    return redirect(url_for('admin_calendar', view='day', date=booking.booking_date.isoformat()))


@app.route('/api/booking/<int:booking_id>/email-status')
@login_required
def get_booking_email_status(booking_id):
    """Get email status for a booking (for AJAX)"""
    booking = Booking.query.get_or_404(booking_id)
    return jsonify({
        'day_after_blocked': booking.day_after_blocked,
        'day_after_sent': booking.day_after_sent,
        'followup_sent': booking.followup_sent
    })


# ==================== CLIENT NOTES ====================

@app.route('/admin/client-notes/add', methods=['POST'])
@login_required
def add_client_note():
    client_email = request.form.get('client_email', '').strip()
    client_name = request.form.get('client_name', '').strip()
    note_text = request.form.get('note', '').strip()
    is_alert = request.form.get('is_alert') == 'on'
    redirect_url = request.form.get('redirect_url', '')

    if not client_email or not note_text:
        flash('Email and note are required.', 'error')
        if redirect_url:
            return redirect(redirect_url)
        return redirect(url_for('admin_clients'))

    note = ClientNote(
        client_email=client_email.lower(),
        client_name=client_name,
        note=note_text,
        is_alert=is_alert
    )
    db.session.add(note)
    db.session.commit()

    # Log the activity
    admin_name = session.get('admin_name', 'Admin')
    ActivityLog.log(
        action_type='client_note_added',
        description=f'{admin_name} added {"⚠️ alert " if is_alert else ""}note for {client_name or client_email}',
        admin_user_id=session.get('admin_user_id'),
        client_email=client_email.lower()
    )

    flash('Note added successfully!', 'success')
    if redirect_url:
        return redirect(redirect_url)
    return redirect(url_for('client_profile', identifier=client_email))


@app.route('/admin/client-notes/edit/<int:note_id>', methods=['POST'])
@login_required
def edit_client_note(note_id):
    note = ClientNote.query.get_or_404(note_id)
    note_text = request.form.get('note', '').strip()
    is_alert = request.form.get('is_alert') == 'on'
    redirect_url = request.form.get('redirect_url', '')

    if not note_text:
        flash('Note cannot be empty.', 'error')
        if redirect_url:
            return redirect(redirect_url)
        return redirect(url_for('client_profile', identifier=note.client_email))

    note.note = note_text
    note.is_alert = is_alert
    note.updated_at = datetime.utcnow()
    db.session.commit()

    flash('Note updated successfully!', 'success')
    if redirect_url:
        return redirect(redirect_url)
    return redirect(url_for('client_profile', identifier=note.client_email))


@app.route('/admin/client-notes/delete/<int:note_id>', methods=['POST'])
@login_required
def delete_client_note(note_id):
    note = ClientNote.query.get_or_404(note_id)
    client_email = note.client_email
    redirect_url = request.form.get('redirect_url', '')

    db.session.delete(note)
    db.session.commit()

    flash('Note deleted.', 'success')
    if redirect_url:
        return redirect(redirect_url)
    return redirect(url_for('client_profile', identifier=client_email))


@app.route('/admin/client-notes/<client_email>')
@login_required
def get_client_notes_api(client_email):
    """API endpoint to get client notes for a given email - used in calendar modal"""
    notes = ClientNote.query.filter(
        ClientNote.client_email.ilike(client_email)
    ).order_by(ClientNote.created_at.desc()).all()

    return jsonify({
        'notes': [{
            'id': n.id,
            'note': n.note,
            'is_alert': n.is_alert,
            'created_at': n.created_at.strftime('%d %b %Y %H:%M')
        } for n in notes],
        'has_alerts': any(n.is_alert for n in notes)
    })


# ==================== CUSTOMER BOOKING ====================

@app.route('/book')
def booking_page():
    # Get categories with their services
    categories = Category.query.filter_by(is_active=True).order_by(Category.display_order).all()

    # Get uncategorized services
    uncategorized = Service.query.filter_by(is_active=True, category_id=None).order_by(Service.display_order).all()

    today = date.today().isoformat()
    max_date = (date.today() + timedelta(days=30)).isoformat()
    return render_template('booking.html', categories=categories, uncategorized=uncategorized, today=today, max_date=max_date)


@app.route('/book/slots', methods=['POST'])
def get_available_slots():
    service_id = request.form['service_id']
    booking_date = request.form['booking_date']

    service = Service.query.get(service_id)
    if not service:
        flash('Service not found', 'error')
        return redirect(url_for('booking_page'))

    booking_date_obj = datetime.strptime(booking_date, '%Y-%m-%d').date()

    # Get categories for template
    categories = Category.query.filter_by(is_active=True).order_by(Category.display_order).all()
    uncategorized = Service.query.filter_by(is_active=True, category_id=None).order_by(Service.display_order).all()
    today = date.today().isoformat()
    max_date = (date.today() + timedelta(days=30)).isoformat()

    # Don't allow booking in the past
    if booking_date_obj < date.today():
        return render_template('booking.html',
                             categories=categories,
                             uncategorized=uncategorized,
                             today=today,
                             max_date=max_date,
                             error="Cannot book dates in the past.")

    # Don't allow booking more than 30 days in advance
    if booking_date_obj > date.today() + timedelta(days=30):
        return render_template('booking.html',
                             categories=categories,
                             uncategorized=uncategorized,
                             today=today,
                             max_date=max_date,
                             error="Bookings can only be made up to 30 days in advance.")

    # Get available slots
    slots = get_available_slots_for_date(service, booking_date_obj)

    if not slots:
        return render_template('booking.html',
                             categories=categories,
                             uncategorized=uncategorized,
                             today=today,
                             max_date=max_date,
                             error="Sorry, no available slots for this date. Please try another date.")

    return render_template('booking.html',
                         categories=categories,
                         uncategorized=uncategorized,
                         today=today,
                         max_date=max_date,
                         selected_service=service,
                         selected_date=booking_date,
                         available_slots=slots)


@app.route('/book/confirm', methods=['POST'])
def confirm_booking():
    """Step 2: After selecting time, redirect to intake form (supports multiple services)"""
    # Support both new multi-service format and legacy single service format
    service_ids_str = request.form.get('service_ids', '')
    service_id = request.form.get('service_id')
    booking_date = request.form['booking_date']
    booking_time = request.form['booking_time']
    total_duration = request.form.get('total_duration', type=int)

    # Parse service IDs
    service_ids = []
    if service_ids_str:
        try:
            service_ids = [int(sid.strip()) for sid in service_ids_str.split(',') if sid.strip()]
        except ValueError:
            flash('Invalid service selection', 'error')
            return redirect(url_for('booking_page'))
    elif service_id:
        service_ids = [int(service_id)]

    if not service_ids:
        flash('Please select at least one service', 'error')
        return redirect(url_for('booking_page'))

    # Get all selected services
    services = Service.query.filter(Service.id.in_(service_ids)).all()
    if not services:
        flash('Services not found', 'error')
        return redirect(url_for('booking_page'))

    # Use primary service (first one) for the booking record
    primary_service = services[0]

    # Calculate total duration if not provided
    if not total_duration:
        total_duration = sum(s.duration_minutes for s in services)

    booking_date_obj = datetime.strptime(booking_date, '%Y-%m-%d').date()

    # Calculate end time based on total duration
    start_mins = time_to_minutes(booking_time)
    end_mins = start_mins + total_duration
    end_time = minutes_to_time(end_mins)

    # Double-check availability before proceeding
    if not check_slot_available(booking_date_obj, booking_time, end_time):
        flash('Sorry, this time slot is no longer available. Please choose another time.', 'error')
        return redirect(url_for('booking_page'))

    # Build additional services info for multi-service bookings
    additional_services = []
    if len(services) > 1:
        for s in services[1:]:
            additional_services.append({
                'id': s.id,
                'name': s.name,
                'duration': s.duration_minutes,
                'price': float(s.price) if s.price else 0
            })

    # Store booking details in session and redirect to intake form
    session['pending_booking'] = {
        'service_id': primary_service.id,
        'service_ids': service_ids,
        'additional_services': additional_services,
        'total_duration': total_duration,
        'booking_date': booking_date,
        'booking_time': booking_time,
        'end_time': end_time
    }

    return redirect(url_for('intake_form'))


@app.route('/book/intake', methods=['GET', 'POST'])
def intake_form():
    """Step 3: Client intake form (supports multiple services)"""
    pending = session.get('pending_booking')
    if not pending:
        flash('Please start a new booking.', 'error')
        return redirect(url_for('booking_page'))

    # Get primary service
    service = Service.query.get(pending['service_id'])
    if not service:
        flash('Service not found', 'error')
        return redirect(url_for('booking_page'))

    # Get all selected services for display
    service_ids = pending.get('service_ids', [pending['service_id']])
    all_services = Service.query.filter(Service.id.in_(service_ids)).all()
    total_duration = pending.get('total_duration', service.duration_minutes)
    total_price = sum(s.price or 0 for s in all_services)

    # Get logged-in user details to pre-fill form
    user = None
    if session.get('customer_logged_in'):
        user = User.query.get(session.get('customer_id'))

    if request.method == 'POST':
        # Parse date of birth
        try:
            dob = datetime.strptime(request.form['date_of_birth'], '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date of birth format', 'error')
            return render_template('intake_form.html', pending=pending, service=service, all_services=all_services, total_duration=total_duration, total_price=total_price, today=date.today().isoformat(), user=user)

        # Calculate if minor (under 18)
        today = date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        is_minor = age < 18

        # Create intake form
        intake = IntakeForm(
            # Personal Info
            full_name=request.form['full_name'],
            date_of_birth=dob,
            email=request.form['email'],
            phone=request.form['phone'],
            address=request.form.get('address', ''),

            # Age Verification
            is_minor=is_minor,
            id_type=request.form.get('id_type', ''),
            parent_guardian_name=request.form.get('parent_guardian_name', '') if is_minor else None,
            parent_guardian_phone=request.form.get('parent_guardian_phone', '') if is_minor else None,
            parental_consent=request.form.get('parental_consent') == 'yes' if is_minor else False,

            # Declaration
            declaration_confirmed=request.form.get('declaration_confirmed') == 'yes'
        )

        db.session.add(intake)
        db.session.flush()  # Get the ID

        # Now create the booking
        booking_date_obj = datetime.strptime(pending['booking_date'], '%Y-%m-%d').date()

        # Final availability check
        if not check_slot_available(booking_date_obj, pending['booking_time'], pending['end_time']):
            db.session.rollback()
            flash('Sorry, this time slot is no longer available. Please choose another time.', 'error')
            session.pop('pending_booking', None)
            return redirect(url_for('booking_page'))

        # Get customer details from the intake form
        customer_name = request.form['full_name']
        customer_email = request.form['email']
        customer_phone = request.form['phone']

        # Check if user is logged in to link booking to account
        user_id = session.get('customer_id') if session.get('customer_logged_in') else None

        # If user is logged in and doesn't have DOB saved, save it from the intake form
        if user_id and user:
            if not user.date_of_birth:
                user.date_of_birth = dob
            # Also update phone if it was empty
            if not user.phone and customer_phone:
                user.phone = customer_phone

        # Build notes with additional services info if multi-service booking
        booking_notes = None
        additional_services = pending.get('additional_services', [])
        if additional_services:
            additional_names = [s['name'] for s in additional_services]
            booking_notes = f"MULTI-SERVICE BOOKING: {service.name} + {', '.join(additional_names)}\nTotal Duration: {total_duration} minutes"

        booking = Booking(
            service_id=pending['service_id'],
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            booking_date=booking_date_obj,
            booking_time=pending['booking_time'],
            end_time=pending['end_time'],
            intake_form_id=intake.id,
            user_id=user_id,
            notes=booking_notes
        )

        db.session.add(booking)
        db.session.commit()

        # Create or update Client record for CRM/marketing
        try:
            from models import Client
            client = Client.find_or_create(
                email=customer_email,
                phone=customer_phone,
                name=customer_name,
                source='booking'
            )
            # Update stats
            client.total_bookings = (client.total_bookings or 0) + 1
            client.last_booking_date = booking_date_obj
            if not client.first_booking_date:
                client.first_booking_date = booking_date_obj
            db.session.commit()
        except Exception as e:
            print(f"[CLIENT] Could not create/update client record: {e}")

        # Build service description for log
        if len(all_services) > 1:
            all_service_names = ' + '.join(s.name for s in all_services)
        else:
            all_service_names = service.name

        # Log the activity (customer booking - no admin_user_id)
        ActivityLog.log(
            action_type='booking_created',
            description=f'{customer_name} booked online: {all_service_names} on {booking_date_obj.strftime("%d %b")} at {pending["booking_time"]}',
            admin_user_id=None,  # Customer booking, not admin
            booking_id=booking.id,
            client_email=customer_email
        )

        # Clear session
        session.pop('pending_booking', None)

        # Print notification
        print("\n" + "=" * 50)
        print("NEW BOOKING RECEIVED!")
        print("=" * 50)
        print(f"Booking ID: {booking.id}")
        print(f"Services: {all_service_names}")
        print(f"Duration: {total_duration} minutes")
        print(f"Date: {booking.booking_date}")
        print(f"Time: {booking.booking_time} - {booking.end_time}")
        print(f"Customer: {booking.customer_name}")
        print(f"Email: {booking.customer_email}")
        if is_minor:
            print("*** NOTE: Client is a minor ***")
        print("=" * 50 + "\n")

        # Send confirmation email
        try:
            from email_service import send_confirmation_email
            send_confirmation_email(booking)
        except Exception as e:
            print(f"[EMAIL ERROR] Failed to send confirmation: {e}")

        return render_template('booking_confirmed.html', booking=booking, service=service, all_services=all_services, total_duration=total_duration, total_price=total_price)

    # GET request - show form with user details pre-filled if logged in
    return render_template('intake_form.html', pending=pending, service=service, all_services=all_services, total_duration=total_duration, total_price=total_price, today=date.today().isoformat(), user=user)


# ==================== ADMIN: INTAKE FORMS ====================

@app.route('/admin/intake-forms')
@login_required
def admin_intake_forms():
    """View all intake forms"""
    show_unreviewed = request.args.get('unreviewed', '') == '1'

    query = IntakeForm.query

    if show_unreviewed:
        query = query.filter_by(reviewed_by_admin=False)

    forms = query.order_by(IntakeForm.created_at.desc()).all()

    return render_template('admin_intake_forms.html',
                         forms=forms,
                         show_unreviewed=show_unreviewed)


@app.route('/admin/intake-forms/<int:form_id>')
@login_required
def view_intake_form(form_id):
    """View single intake form details"""
    intake = IntakeForm.query.get_or_404(form_id)
    return render_template('view_intake_form.html', intake=intake)


@app.route('/admin/intake-forms/<int:form_id>/review', methods=['POST'])
@login_required
def review_intake_form(form_id):
    """Mark intake form as reviewed"""
    intake = IntakeForm.query.get_or_404(form_id)
    intake.reviewed_by_admin = True
    intake.admin_notes = request.form.get('admin_notes', '')
    db.session.commit()
    flash('Intake form marked as reviewed.', 'success')
    return redirect(url_for('view_intake_form', form_id=form_id))


# ==================== ADMIN: SETTINGS ====================

@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    """Configure email and notification settings"""
    test_result = None

    if request.method == 'POST':
        # Check if this is a test email request
        if request.form.get('test_email'):
            from email_service import send_test_email
            smtp_username = request.form.get('smtp_username', '')
            if smtp_username:
                # Save settings first
                save_settings_from_form(request.form)
                # Then send test
                success = send_test_email(smtp_username)
                test_result = 'success' if success else 'error'
            else:
                flash('Please enter an SMTP username to send test email.', 'error')
        else:
            # Save settings
            save_settings_from_form(request.form)
            flash('Settings saved successfully!', 'success')
            return redirect(url_for('admin_settings'))

    # Get current settings
    settings = {
        'business_name': Settings.get('business_name'),
        'business_email': Settings.get('business_email'),
        'business_phone': Settings.get('business_phone'),
        'business_address': Settings.get('business_address'),
        'email_enabled': Settings.get('email_enabled'),
        'email_provider': Settings.get('email_provider', 'brevo'),
        'brevo_api_key': Settings.get('brevo_api_key'),
        'email_from_address': Settings.get('email_from_address'),
        'email_from_name': Settings.get('email_from_name'),
        'smtp_server': Settings.get('smtp_server'),
        'smtp_port': Settings.get('smtp_port'),
        'smtp_username': Settings.get('smtp_username'),
        'smtp_password': Settings.get('smtp_password'),
        'smtp_use_tls': Settings.get('smtp_use_tls'),
        'send_confirmation_email': Settings.get('send_confirmation_email'),
        'send_reminder_email': Settings.get('send_reminder_email'),
        'reminder_hours_before': Settings.get('reminder_hours_before'),
        'send_day_after_email': Settings.get('send_day_after_email', 'true'),  # Default to enabled
        'send_followup_email': Settings.get('send_followup_email', 'true'),  # Default to enabled
        'google_review_link': Settings.get('google_review_link'),
    }

    return render_template('admin_settings.html', settings=settings, test_result=test_result)


def save_settings_from_form(form):
    """Save settings from form data"""
    # Business info
    Settings.set('business_name', form.get('business_name', ''))
    Settings.set('business_email', form.get('business_email', ''))
    Settings.set('business_phone', form.get('business_phone', ''))
    Settings.set('business_address', form.get('business_address', ''))

    # Email settings
    Settings.set('email_enabled', 'true' if form.get('email_enabled') else 'false')
    Settings.set('email_provider', form.get('email_provider', 'brevo'))

    # Brevo settings
    if form.get('brevo_api_key'):  # Only update if provided
        Settings.set('brevo_api_key', form.get('brevo_api_key', ''))
    Settings.set('email_from_address', form.get('email_from_address', ''))
    Settings.set('email_from_name', form.get('email_from_name', ''))

    # Legacy SMTP settings
    Settings.set('smtp_server', form.get('smtp_server', ''))
    Settings.set('smtp_port', form.get('smtp_port', '587'))
    Settings.set('smtp_username', form.get('smtp_username', ''))
    if form.get('smtp_password'):  # Only update if provided
        Settings.set('smtp_password', form.get('smtp_password', ''))
    Settings.set('smtp_use_tls', 'true' if form.get('smtp_use_tls') else 'false')

    # Notification settings
    Settings.set('send_confirmation_email', 'true' if form.get('send_confirmation_email') else 'false')
    Settings.set('send_reminder_email', 'true' if form.get('send_reminder_email') else 'false')
    Settings.set('reminder_hours_before', form.get('reminder_hours_before', '24'))
    Settings.set('send_day_after_email', 'true' if form.get('send_day_after_email') else 'false')
    Settings.set('send_followup_email', 'true' if form.get('send_followup_email') else 'false')
    Settings.set('google_review_link', form.get('google_review_link', ''))


# ==================== CLIENT MANAGEMENT ====================

@app.route('/admin/clients')
@login_required
def admin_clients():
    """Client list with search and filtering"""
    from models import Client, ClientTag

    # Get filter parameters
    search = request.args.get('search', '').strip()
    tag_id = request.args.get('tag', type=int)
    opt_in = request.args.get('opt_in')
    page = request.args.get('page', 1, type=int)
    per_page = 50

    # Build query
    query = Client.query

    if search:
        search_term = f'%{search}%'
        query = query.filter(
            db.or_(
                Client.name.ilike(search_term),
                Client.email.ilike(search_term),
                Client.phone.ilike(search_term)
            )
        )

    if tag_id:
        query = query.filter(Client.tags.any(id=tag_id))

    if opt_in == 'yes':
        query = query.filter(Client.email_opt_in == True, Client.unsubscribed_at.is_(None))
    elif opt_in == 'no':
        query = query.filter(db.or_(Client.email_opt_in == False, Client.unsubscribed_at.isnot(None)))

    # Order by most recent
    query = query.order_by(Client.created_at.desc())

    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    clients = pagination.items

    # Get all tags for filter dropdown
    tags = ClientTag.query.order_by(ClientTag.name).all()

    # Stats
    total_clients = Client.query.count()
    opted_in_count = Client.query.filter(Client.email_opt_in == True, Client.unsubscribed_at.is_(None)).count()

    return render_template('admin_clients.html',
        clients=clients,
        pagination=pagination,
        tags=tags,
        search=search,
        selected_tag=tag_id,
        opt_in=opt_in,
        total_clients=total_clients,
        opted_in_count=opted_in_count
    )


@app.route('/admin/clients/sync-from-bookings', methods=['POST'])
@login_required
def admin_clients_sync_from_bookings():
    """Import all existing booking customers as clients"""
    from models import Client, Booking
    from sqlalchemy import func

    # Get all unique customers from bookings
    # Group by email to get stats (use max() for phone/name to get most recent values)
    booking_stats = db.session.query(
        Booking.customer_email,
        func.max(Booking.customer_phone).label('customer_phone'),
        func.max(Booking.customer_name).label('customer_name'),
        func.count(Booking.id).label('total_bookings'),
        func.min(Booking.booking_date).label('first_booking'),
        func.max(Booking.booking_date).label('last_booking')
    ).filter(
        Booking.customer_email.isnot(None),
        Booking.customer_email != ''
    ).group_by(
        Booking.customer_email
    ).all()

    created = 0
    updated = 0

    for stat in booking_stats:
        # Check if client already exists
        existing = Client.query.filter(
            db.or_(
                Client.email == stat.customer_email,
                db.and_(Client.phone == stat.customer_phone, stat.customer_phone != None, stat.customer_phone != '')
            )
        ).first()

        if existing:
            # Update stats
            existing.total_bookings = stat.total_bookings
            existing.first_booking_date = stat.first_booking
            existing.last_booking_date = stat.last_booking
            if not existing.name and stat.customer_name:
                existing.name = stat.customer_name
            if not existing.phone and stat.customer_phone:
                existing.phone = stat.customer_phone
            updated += 1
        else:
            # Create new client
            import secrets
            client = Client(
                email=stat.customer_email,
                phone=stat.customer_phone,
                name=stat.customer_name,
                source='booking',
                email_opt_in=True,
                unsubscribe_token=secrets.token_urlsafe(32),
                total_bookings=stat.total_bookings,
                first_booking_date=stat.first_booking,
                last_booking_date=stat.last_booking
            )
            db.session.add(client)
            created += 1

    db.session.commit()

    flash(f'Synced clients from bookings: {created} created, {updated} updated', 'success')
    return redirect(url_for('admin_clients'))


@app.route('/admin/clients/import', methods=['GET', 'POST'])
@login_required
def admin_clients_import():
    """Import clients from CSV"""
    from models import Client, ClientTag, ClientTagAssignment
    import csv
    import io
    import secrets

    import_result = None

    if request.method == 'POST':
        if 'csv_file' not in request.files:
            flash('No file selected', 'error')
            return redirect(url_for('admin_clients_import'))

        file = request.files['csv_file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(url_for('admin_clients_import'))

        if not file.filename.endswith('.csv'):
            flash('Please upload a CSV file', 'error')
            return redirect(url_for('admin_clients_import'))

        # Get column mappings
        col_name = request.form.get('col_name', '')
        col_email = request.form.get('col_email', '')
        col_phone = request.form.get('col_phone', '')
        col_tags = request.form.get('col_tags', '')
        duplicate_action = request.form.get('duplicate_action', 'update')

        # Parse CSV
        try:
            content = file.read().decode('utf-8-sig')  # Handle BOM
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)
        except Exception as e:
            flash(f'Error reading CSV: {str(e)}', 'error')
            return redirect(url_for('admin_clients_import'))

        if len(rows) < 2:
            flash('CSV file is empty or has no data rows', 'error')
            return redirect(url_for('admin_clients_import'))

        headers = rows[0]
        data_rows = rows[1:]

        # Convert column indices
        name_idx = int(col_name) if col_name else None
        email_idx = int(col_email) if col_email else None
        phone_idx = int(col_phone) if col_phone else None
        tags_idx = int(col_tags) if col_tags else None

        if email_idx is None and phone_idx is None:
            flash('You must map at least Email or Phone column', 'error')
            return redirect(url_for('admin_clients_import'))

        # Process rows
        created = 0
        updated = 0
        skipped = 0
        errors = []

        for row_num, row in enumerate(data_rows, start=2):
            try:
                # Extract values
                name = row[name_idx].strip() if name_idx is not None and name_idx < len(row) else None
                email = row[email_idx].strip().lower() if email_idx is not None and email_idx < len(row) else None
                phone = row[phone_idx].strip() if phone_idx is not None and phone_idx < len(row) else None
                tags_str = row[tags_idx].strip() if tags_idx is not None and tags_idx < len(row) else None

                # Skip empty rows
                if not email and not phone:
                    skipped += 1
                    continue

                # Find existing client by email OR phone
                existing = None
                if email:
                    existing = Client.query.filter_by(email=email).first()
                if not existing and phone:
                    # Normalize phone for comparison
                    normalized = ''.join(filter(str.isdigit, phone))
                    if normalized:
                        for c in Client.query.filter(Client.phone.isnot(None)).all():
                            c_norm = ''.join(filter(str.isdigit, c.phone)) if c.phone else ''
                            if c_norm and c_norm == normalized:
                                existing = c
                                break

                if existing:
                    if duplicate_action == 'skip':
                        skipped += 1
                        continue
                    # Update existing
                    if name and not existing.name:
                        existing.name = name
                    if email and not existing.email:
                        existing.email = email
                    if phone and not existing.phone:
                        existing.phone = phone
                    updated += 1
                    client = existing
                else:
                    # Create new client
                    client = Client(
                        name=name,
                        email=email,
                        phone=phone,
                        source='import',
                        unsubscribe_token=secrets.token_urlsafe(32)
                    )
                    db.session.add(client)
                    created += 1

                # Handle tags
                if tags_str:
                    tag_names = [t.strip() for t in tags_str.split(',') if t.strip()]
                    for tag_name in tag_names:
                        # Find or create tag
                        tag = ClientTag.query.filter_by(name=tag_name).first()
                        if not tag:
                            tag = ClientTag(name=tag_name)
                            db.session.add(tag)
                            db.session.flush()

                        # Add tag to client if not already assigned
                        if tag not in client.tags:
                            client.tags.append(tag)

            except Exception as e:
                errors.append(f'Row {row_num}: {str(e)}')

        db.session.commit()

        import_result = {
            'created': created,
            'updated': updated,
            'skipped': skipped,
            'errors': errors
        }

        if not errors:
            flash(f'Import complete! Created {created}, updated {updated}, skipped {skipped}', 'success')

    return render_template('admin_clients_import.html', import_result=import_result)


@app.route('/admin/clients/<int:client_id>')
@login_required
def admin_client_detail(client_id):
    """View/edit client details"""
    from models import Client, ClientTag, ClientNote, Booking

    client = Client.query.get_or_404(client_id)

    # Get client's bookings
    bookings = Booking.query.filter(
        db.or_(
            Booking.customer_email == client.email,
            Booking.customer_phone == client.phone
        ) if client.email and client.phone else (
            Booking.customer_email == client.email if client.email else Booking.customer_phone == client.phone
        )
    ).order_by(Booking.booking_date.desc()).limit(20).all()

    # Get client notes (linked by email)
    notes = []
    if client.email:
        notes = ClientNote.query.filter_by(client_email=client.email).order_by(ClientNote.created_at.desc()).all()

    # All tags for assignment
    all_tags = ClientTag.query.order_by(ClientTag.name).all()

    return render_template('admin_client_detail.html',
        client=client,
        bookings=bookings,
        notes=notes,
        all_tags=all_tags
    )


@app.route('/admin/clients/<int:client_id>/edit', methods=['POST'])
@login_required
def admin_client_edit(client_id):
    """Update client details"""
    from models import Client

    client = Client.query.get_or_404(client_id)

    client.name = request.form.get('name', client.name)
    client.email = request.form.get('email', client.email)
    client.phone = request.form.get('phone', client.phone)
    client.notes = request.form.get('notes', client.notes)
    client.email_opt_in = request.form.get('email_opt_in') == 'true'

    db.session.commit()
    flash('Client updated successfully', 'success')
    return redirect(url_for('admin_client_detail', client_id=client_id))


@app.route('/admin/clients/<int:client_id>/tags', methods=['POST'])
@login_required
def admin_client_tags(client_id):
    """Update client tags"""
    from models import Client, ClientTag

    client = Client.query.get_or_404(client_id)
    tag_ids = request.form.getlist('tags')

    # Clear existing tags and add selected ones
    client.tags = []
    for tag_id in tag_ids:
        tag = ClientTag.query.get(int(tag_id))
        if tag:
            client.tags.append(tag)

    db.session.commit()
    flash('Tags updated', 'success')
    return redirect(url_for('admin_client_detail', client_id=client_id))


@app.route('/admin/clients/tags')
@login_required
def admin_client_tags_list():
    """Manage client tags"""
    from models import ClientTag

    tags = ClientTag.query.order_by(ClientTag.name).all()
    return render_template('admin_client_tags.html', tags=tags)


@app.route('/admin/clients/tags/add', methods=['POST'])
@login_required
def admin_client_tag_add():
    """Create a new tag"""
    from models import ClientTag

    name = request.form.get('name', '').strip()
    color = request.form.get('color', '#6366f1')

    if not name:
        flash('Tag name is required', 'error')
        return redirect(url_for('admin_client_tags_list'))

    if ClientTag.query.filter_by(name=name).first():
        flash('Tag already exists', 'error')
        return redirect(url_for('admin_client_tags_list'))

    tag = ClientTag(name=name, color=color)
    db.session.add(tag)
    db.session.commit()

    flash(f'Tag "{name}" created', 'success')
    return redirect(url_for('admin_client_tags_list'))


@app.route('/admin/clients/tags/<int:tag_id>/delete', methods=['POST'])
@login_required
def admin_client_tag_delete(tag_id):
    """Delete a tag"""
    from models import ClientTag

    tag = ClientTag.query.get_or_404(tag_id)
    name = tag.name

    db.session.delete(tag)
    db.session.commit()

    flash(f'Tag "{name}" deleted', 'success')
    return redirect(url_for('admin_client_tags_list'))


# ==================== EMAIL CAMPAIGNS ====================

@app.route('/admin/campaigns')
@login_required
def admin_campaigns():
    """List all email campaigns"""
    from models import EmailCampaign

    campaigns = EmailCampaign.query.order_by(EmailCampaign.created_at.desc()).all()
    return render_template('admin_campaigns.html', campaigns=campaigns)


@app.route('/admin/campaigns/new', methods=['GET', 'POST'])
@login_required
def admin_campaign_new():
    """Create a new email campaign"""
    from models import EmailCampaign, EmailTemplate, ClientTag, Client

    if request.method == 'POST':
        campaign = EmailCampaign(
            name=request.form.get('name', 'Untitled Campaign'),
            subject=request.form.get('subject', ''),
            content=request.form.get('content', ''),
            status='draft'
        )

        # Handle targeting
        if request.form.get('target_all') == 'true':
            campaign.target_all = True
        else:
            campaign.target_all = False
            tag_ids = request.form.getlist('target_tags')
            campaign.set_target_tags(tag_ids)

        db.session.add(campaign)
        db.session.commit()

        flash('Campaign created', 'success')
        return redirect(url_for('admin_campaign_edit', campaign_id=campaign.id))

    # Get data for form
    templates = EmailTemplate.query.order_by(EmailTemplate.name).all()
    tags = ClientTag.query.order_by(ClientTag.name).all()
    total_opted_in = Client.query.filter(
        Client.email_opt_in == True,
        Client.unsubscribed_at.is_(None),
        Client.email.isnot(None)
    ).count()

    return render_template('admin_campaign_edit.html',
        campaign=None,
        templates=templates,
        tags=tags,
        total_opted_in=total_opted_in
    )


@app.route('/admin/campaigns/<int:campaign_id>', methods=['GET', 'POST'])
@login_required
def admin_campaign_edit(campaign_id):
    """Edit an existing campaign"""
    from models import EmailCampaign, EmailTemplate, ClientTag, Client

    campaign = EmailCampaign.query.get_or_404(campaign_id)

    if request.method == 'POST':
        # Don't allow editing sent campaigns
        if campaign.status == 'sent':
            flash('Cannot edit a sent campaign', 'error')
            return redirect(url_for('admin_campaign_edit', campaign_id=campaign_id))

        campaign.name = request.form.get('name', campaign.name)
        campaign.subject = request.form.get('subject', campaign.subject)
        campaign.content = request.form.get('content', campaign.content)

        # Handle targeting
        if request.form.get('target_all') == 'true':
            campaign.target_all = True
            campaign.target_tag_ids = None
        else:
            campaign.target_all = False
            tag_ids = request.form.getlist('target_tags')
            campaign.set_target_tags(tag_ids)

        db.session.commit()
        flash('Campaign saved', 'success')
        return redirect(url_for('admin_campaign_edit', campaign_id=campaign_id))

    templates = EmailTemplate.query.order_by(EmailTemplate.name).all()
    tags = ClientTag.query.order_by(ClientTag.name).all()
    total_opted_in = Client.query.filter(
        Client.email_opt_in == True,
        Client.unsubscribed_at.is_(None),
        Client.email.isnot(None)
    ).count()

    return render_template('admin_campaign_edit.html',
        campaign=campaign,
        templates=templates,
        tags=tags,
        total_opted_in=total_opted_in
    )


@app.route('/admin/campaigns/<int:campaign_id>/send', methods=['POST'])
@login_required
def admin_campaign_send(campaign_id):
    """Start sending a campaign"""
    from models import EmailCampaign, CampaignRecipient, Client, ClientTag

    campaign = EmailCampaign.query.get_or_404(campaign_id)

    if campaign.status not in ['draft']:
        flash('Campaign has already been sent or is sending', 'error')
        return redirect(url_for('admin_campaign_edit', campaign_id=campaign_id))

    # Build recipient list
    query = Client.query.filter(
        Client.email_opt_in == True,
        Client.unsubscribed_at.is_(None),
        Client.email.isnot(None)
    )

    # Filter by tags if not targeting all
    if not campaign.target_all and campaign.target_tag_ids:
        tag_ids = campaign.get_target_tags()
        query = query.filter(Client.tags.any(ClientTag.id.in_(tag_ids)))

    clients = query.all()

    if not clients:
        flash('No eligible recipients for this campaign', 'error')
        return redirect(url_for('admin_campaign_edit', campaign_id=campaign_id))

    # Create recipient records
    for client in clients:
        recipient = CampaignRecipient(
            campaign_id=campaign.id,
            client_id=client.id,
            status='pending'
        )
        db.session.add(recipient)

    campaign.total_recipients = len(clients)
    campaign.status = 'sending'
    db.session.commit()

    # Send emails (in batches to avoid timeout)
    from email_service import send_campaign_email

    sent_count = 0
    for client in clients[:50]:  # Send first batch immediately
        if send_campaign_email(campaign, client):
            sent_count += 1

    remaining = len(clients) - 50
    if remaining > 0:
        flash(f'Sending started! {sent_count} emails sent, {remaining} remaining (will continue in background)', 'success')
    else:
        campaign.status = 'sent'
        campaign.sent_at = datetime.utcnow()
        db.session.commit()
        flash(f'Campaign sent to {sent_count} recipients!', 'success')

    return redirect(url_for('admin_campaign_edit', campaign_id=campaign_id))


@app.route('/admin/campaigns/<int:campaign_id>/delete', methods=['POST'])
@login_required
def admin_campaign_delete(campaign_id):
    """Delete a campaign"""
    from models import EmailCampaign

    campaign = EmailCampaign.query.get_or_404(campaign_id)

    if campaign.status == 'sending':
        flash('Cannot delete a campaign that is currently sending', 'error')
        return redirect(url_for('admin_campaigns'))

    db.session.delete(campaign)
    db.session.commit()

    flash('Campaign deleted', 'success')
    return redirect(url_for('admin_campaigns'))


@app.route('/admin/campaigns/templates')
@login_required
def admin_campaign_templates():
    """Manage email templates"""
    from models import EmailTemplate

    templates = EmailTemplate.query.order_by(EmailTemplate.category, EmailTemplate.name).all()
    return render_template('admin_campaign_templates.html', templates=templates)


@app.route('/unsubscribe/<token>')
def unsubscribe(token):
    """Handle email unsubscribe"""
    from models import Client

    client = Client.query.filter_by(unsubscribe_token=token).first()

    if not client:
        return render_template('unsubscribe.html', success=False, error='Invalid unsubscribe link')

    if request.args.get('confirm') == 'yes':
        client.email_opt_in = False
        client.unsubscribed_at = datetime.utcnow()
        db.session.commit()
        return render_template('unsubscribe.html', success=True, client=client)

    return render_template('unsubscribe.html', success=None, client=client, token=token)


# ==================== API ENDPOINTS (for future embedding) ====================

@app.route('/api/services')
def api_services():
    """Get all active services"""
    services = Service.query.filter_by(is_active=True).all()
    return jsonify([{
        'id': s.id,
        'name': s.name,
        'duration_minutes': s.duration_minutes,
        'price': s.price,
        'description': s.description
    } for s in services])


@app.route('/api/slots/<int:service_id>/<booking_date>')
def api_slots(service_id, booking_date):
    """Get available slots for a service on a specific date"""
    service = Service.query.get(service_id)
    if not service:
        return jsonify({'error': 'Service not found'}), 404

    booking_date_obj = datetime.strptime(booking_date, '%Y-%m-%d').date()
    slots = get_available_slots_for_date(service, booking_date_obj)

    return jsonify({
        'service': service.name,
        'date': booking_date,
        'slots': slots
    })


@app.route('/api/available-slots')
def api_available_slots():
    """Get available slots for services on a specific date (supports multiple services)"""
    # Support both single service_id and multiple service_ids
    service_ids_str = request.args.get('service_ids', '')
    service_id = request.args.get('service_id', type=int)
    date_str = request.args.get('date')
    total_duration = request.args.get('total_duration', type=int)

    if not date_str:
        return jsonify({'error': 'date required', 'slots': []})

    # Parse service IDs - support comma-separated list or single ID
    service_ids = []
    if service_ids_str:
        try:
            service_ids = [int(sid.strip()) for sid in service_ids_str.split(',') if sid.strip()]
        except ValueError:
            return jsonify({'error': 'Invalid service_ids format', 'slots': []})
    elif service_id:
        service_ids = [service_id]

    if not service_ids:
        return jsonify({'error': 'service_id or service_ids required', 'slots': []})

    # Get services and calculate total duration if not provided
    services = Service.query.filter(Service.id.in_(service_ids)).all()
    if not services:
        return jsonify({'error': 'No services found', 'slots': []})

    # Calculate total duration from services if not explicitly provided
    if not total_duration:
        total_duration = sum(s.duration_minutes for s in services)

    try:
        booking_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format', 'slots': []})

    # Get slots using the total duration
    slots = get_available_slots_for_duration(total_duration, booking_date_obj)

    service_names = ', '.join(s.name for s in services)
    return jsonify({
        'services': service_names,
        'date': date_str,
        'total_duration': total_duration,
        'slots': slots
    })


def start_reminder_scheduler():
    """Background thread to check and send reminders and follow-ups periodically"""
    def run_scheduler():
        followup_counter = 0  # Track iterations for daily follow-up check
        while True:
            try:
                from email_service import check_and_send_reminders, check_and_send_followups, check_and_send_day_after_emails

                # Check reminders every 30 minutes
                check_and_send_reminders(app)

                # Check day-after emails every 30 minutes (will only send if 24hrs have passed)
                check_and_send_day_after_emails(app)

                # Check 6-week follow-ups once per day (every 48 iterations = 24 hours)
                followup_counter += 1
                if followup_counter >= 48:
                    check_and_send_followups(app)
                    followup_counter = 0

            except Exception as e:
                print(f"[SCHEDULER ERROR] {e}")
            # Check every 30 minutes
            time.sleep(30 * 60)

    thread = threading.Thread(target=run_scheduler, daemon=True)
    thread.start()
    print("[SCHEDULER] Reminder & follow-up scheduler started (reminders every 30 min, day-after & 6-week follow-ups daily)")


# ==================== CUSTOMER ACCOUNT SYSTEM ====================

def customer_login_required(f):
    """Decorator to require customer login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('customer_logged_in'):
            flash('Please log in to access your account.', 'error')
            return redirect(url_for('customer_login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/customer/register', methods=['GET', 'POST'])
def customer_register():
    """Customer registration page"""
    if session.get('customer_logged_in'):
        return redirect(url_for('customer_dashboard'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        phone = request.form.get('phone', '').strip()

        # Validation
        if not name or not email or not password:
            flash('Please fill in all required fields.', 'error')
            return render_template('register.html', name=name, email=email, phone=phone)

        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('register.html', name=name, email=email, phone=phone)

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return render_template('register.html', name=name, email=email, phone=phone)

        # Check if email already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('An account with this email already exists. Please log in.', 'error')
            return redirect(url_for('customer_login'))

        # Create new user
        user = User(name=name, email=email, phone=phone)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # Link any existing bookings with this email to the new account
        existing_bookings = Booking.query.filter_by(customer_email=email, user_id=None).all()
        for booking in existing_bookings:
            booking.user_id = user.id
        db.session.commit()

        print(f"\n[NEW USER] {name} ({email}) registered")

        # Auto-login after registration
        session['customer_logged_in'] = True
        session['customer_id'] = user.id
        session['customer_name'] = user.name
        session['customer_email'] = user.email

        flash('Account created successfully! Welcome to White Thorn Piercing.', 'success')
        return redirect(url_for('customer_dashboard'))

    return render_template('register.html')


@app.route('/customer/login', methods=['GET', 'POST'])
def customer_login():
    """Customer login page"""
    if session.get('customer_logged_in'):
        return redirect(url_for('customer_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        user = User.query.filter_by(email=email, is_active=True).first()

        if user and user.check_password(password):
            session['customer_logged_in'] = True
            session['customer_id'] = user.id
            session['customer_name'] = user.name
            session['customer_email'] = user.email

            print(f"\n[CUSTOMER LOGIN] {user.name} ({user.email}) logged in")

            flash(f'Welcome back, {user.name}!', 'success')

            # Redirect to next page if specified
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            return redirect(url_for('customer_dashboard'))
        else:
            flash('Invalid email or password.', 'error')

    return render_template('login.html')


@app.route('/customer/logout')
def customer_logout():
    """Customer logout"""
    session.pop('customer_logged_in', None)
    session.pop('customer_id', None)
    session.pop('customer_name', None)
    session.pop('customer_email', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))


@app.route('/customer/dashboard')
@customer_login_required
def customer_dashboard():
    """Customer dashboard showing overview"""
    # Auto-complete past appointments first
    auto_complete_past_appointments()

    user_id = session.get('customer_id')
    user = User.query.get(user_id)

    # Get next upcoming appointment
    today = date.today()
    next_appointment = Booking.query.filter(
        Booking.user_id == user_id,
        Booking.booking_date >= today,
        Booking.status.in_(['confirmed'])
    ).order_by(Booking.booking_date, Booking.booking_time).first()

    # Get total bookings count
    total_bookings = Booking.query.filter_by(user_id=user_id).count()

    # Get count of completed bookings
    completed_bookings = Booking.query.filter(
        Booking.user_id == user_id,
        Booking.status == 'completed'
    ).count()

    return render_template('customer_dashboard.html',
                         user=user,
                         next_appointment=next_appointment,
                         total_bookings=total_bookings,
                         completed_bookings=completed_bookings)


@app.route('/customer/appointments')
@customer_login_required
def customer_appointments():
    """Show upcoming appointments"""
    # Auto-complete past appointments first
    auto_complete_past_appointments()

    user_id = session.get('customer_id')
    today = date.today()
    now = datetime.now()

    # Get all future bookings (confirmed only)
    appointments = Booking.query.filter(
        Booking.user_id == user_id,
        Booking.booking_date >= today,
        Booking.status == 'confirmed'
    ).order_by(Booking.booking_date, Booking.booking_time).all()

    # Add can_modify flag (only if >24 hours away)
    for apt in appointments:
        apt_datetime = datetime.combine(apt.booking_date, datetime.strptime(apt.booking_time, '%H:%M').time())
        hours_until = (apt_datetime - now).total_seconds() / 3600
        apt.can_modify = hours_until > 24
        apt.hours_until = hours_until

    return render_template('customer_appointments.html', appointments=appointments)


@app.route('/customer/history')
@customer_login_required
def customer_history():
    """Show booking history (past appointments)"""
    # Auto-complete past appointments first
    auto_complete_past_appointments()

    user_id = session.get('customer_id')

    # Get all completed and no-show bookings (past appointments)
    history = Booking.query.filter(
        Booking.user_id == user_id,
        Booking.status.in_(['completed', 'no_show'])
    ).order_by(Booking.booking_date.desc(), Booking.booking_time.desc()).all()

    # Get unique services for aftercare links
    service_ids = set(b.service_id for b in history if b.status == 'completed')

    # Get aftercare guides for these services
    aftercare_map = {}
    for service_id in service_ids:
        aftercare = Aftercare.query.filter_by(service_id=service_id, is_active=True).first()
        if aftercare:
            aftercare_map[service_id] = aftercare

    return render_template('customer_history.html', history=history, aftercare_map=aftercare_map)


@app.route('/customer/reschedule/<int:booking_id>', methods=['GET', 'POST'])
@customer_login_required
def customer_reschedule(booking_id):
    """Reschedule a booking"""
    user_id = session.get('customer_id')

    # Get the booking and verify ownership
    booking = Booking.query.filter_by(id=booking_id, user_id=user_id).first()
    if not booking:
        flash('Booking not found.', 'error')
        return redirect(url_for('customer_appointments'))

    # Check if booking can be modified (>24 hours away)
    now = datetime.now()
    apt_datetime = datetime.combine(booking.booking_date, datetime.strptime(booking.booking_time, '%H:%M').time())
    hours_until = (apt_datetime - now).total_seconds() / 3600

    if hours_until <= 24:
        flash('Bookings can only be rescheduled more than 24 hours in advance. Please contact us to make changes.', 'error')
        return redirect(url_for('customer_appointments'))

    if request.method == 'POST':
        new_date = request.form.get('booking_date')
        new_time = request.form.get('booking_time')

        if not new_date or not new_time:
            flash('Please select a new date and time.', 'error')
            return redirect(url_for('customer_reschedule', booking_id=booking_id))

        new_booking_date = datetime.strptime(new_date, '%Y-%m-%d').date()

        # Calculate new end time
        service = booking.service
        start_parts = new_time.split(':')
        start_minutes = int(start_parts[0]) * 60 + int(start_parts[1])
        end_minutes = start_minutes + service.duration_minutes
        new_end_time = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"

        # Update booking
        old_date = booking.booking_date
        old_time = booking.booking_time

        booking.booking_date = new_booking_date
        booking.booking_time = new_time
        booking.end_time = new_end_time
        booking.reminder_sent = False  # Reset reminder so they get a new one
        db.session.commit()

        print(f"\n[RESCHEDULED] Booking #{booking.id}")
        print(f"  Customer: {booking.customer_name}")
        print(f"  Old: {old_date} {old_time}")
        print(f"  New: {new_booking_date} {new_time}")

        # Send reschedule confirmation email
        from email_service import send_reschedule_email
        send_reschedule_email(booking, old_date, old_time)

        flash('Your appointment has been rescheduled successfully!', 'success')
        return redirect(url_for('customer_appointments'))

    # GET - show available slots for rescheduling
    service = booking.service
    today = date.today()
    max_date = today + timedelta(days=30)

    return render_template('reschedule_booking.html',
                         booking=booking,
                         service=service,
                         today=today.isoformat(),
                         max_date=max_date.isoformat())


@app.route('/customer/cancel/<int:booking_id>', methods=['POST'])
@customer_login_required
def customer_cancel(booking_id):
    """Cancel a booking"""
    user_id = session.get('customer_id')

    # Get the booking and verify ownership
    booking = Booking.query.filter_by(id=booking_id, user_id=user_id).first()
    if not booking:
        flash('Booking not found.', 'error')
        return redirect(url_for('customer_appointments'))

    # Check if booking can be modified (>24 hours away)
    now = datetime.now()
    apt_datetime = datetime.combine(booking.booking_date, datetime.strptime(booking.booking_time, '%H:%M').time())
    hours_until = (apt_datetime - now).total_seconds() / 3600

    if hours_until <= 24:
        flash('Bookings can only be cancelled more than 24 hours in advance. Please contact us to make changes.', 'error')
        return redirect(url_for('customer_appointments'))

    # Cancel the booking
    booking.status = 'cancelled'
    db.session.commit()

    print(f"\n[CUSTOMER CANCELLED] Booking #{booking.id}")
    print(f"  Customer: {booking.customer_name}")
    print(f"  Service: {booking.service.name}")
    print(f"  Date: {booking.booking_date} {booking.booking_time}")

    flash('Your appointment has been cancelled.', 'success')
    return redirect(url_for('customer_appointments'))


@app.route('/customer/aftercare')
@customer_login_required
def customer_aftercare():
    """Show aftercare advice for customer's past services"""
    # Auto-complete past appointments first
    auto_complete_past_appointments()

    user_id = session.get('customer_id')

    # Get all completed bookings for this user
    completed_bookings = Booking.query.filter(
        Booking.user_id == user_id,
        Booking.status == 'completed'
    ).all()

    # Get unique services
    service_ids = set(b.service_id for b in completed_bookings)
    services_with_aftercare = []

    for service_id in service_ids:
        service = Service.query.get(service_id)
        aftercare = Aftercare.query.filter_by(service_id=service_id, is_active=True).first()
        if aftercare:
            services_with_aftercare.append({
                'service': service,
                'aftercare': aftercare,
                'last_booking': max(b.booking_date for b in completed_bookings if b.service_id == service_id)
            })

    # Also get general aftercare (no service_id)
    general_aftercare = Aftercare.query.filter_by(service_id=None, is_active=True).all()

    return render_template('customer_aftercare.html',
                         services_with_aftercare=services_with_aftercare,
                         general_aftercare=general_aftercare)


@app.route('/customer/aftercare/<int:aftercare_id>')
@customer_login_required
def customer_aftercare_detail(aftercare_id):
    """View specific aftercare guide"""
    aftercare = Aftercare.query.get_or_404(aftercare_id)
    return render_template('customer_aftercare_detail.html', aftercare=aftercare)


# ==================== ADMIN: AFTERCARE MANAGEMENT ====================

@app.route('/admin/aftercare')
@login_required
def admin_aftercare():
    """Admin aftercare management page"""
    aftercare_items = Aftercare.query.order_by(Aftercare.created_at.desc()).all()
    return render_template('admin_aftercare.html', aftercare_items=aftercare_items)


@app.route('/admin/aftercare/add', methods=['GET', 'POST'])
@login_required
def add_aftercare():
    """Add new aftercare guide"""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        service_id = request.form.get('service_id')

        if not title or not content:
            flash('Please provide a title and content.', 'error')
            return redirect(url_for('add_aftercare'))

        aftercare = Aftercare(
            title=title,
            content=content,
            service_id=int(service_id) if service_id else None
        )
        db.session.add(aftercare)
        db.session.commit()

        flash('Aftercare guide added successfully!', 'success')
        return redirect(url_for('admin_aftercare'))

    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    return render_template('add_aftercare.html', services=services)


@app.route('/admin/aftercare/edit/<int:aftercare_id>', methods=['GET', 'POST'])
@login_required
def edit_aftercare(aftercare_id):
    """Edit aftercare guide"""
    aftercare = Aftercare.query.get_or_404(aftercare_id)

    if request.method == 'POST':
        aftercare.title = request.form.get('title', '').strip()
        aftercare.content = request.form.get('content', '').strip()
        service_id = request.form.get('service_id')
        aftercare.service_id = int(service_id) if service_id else None
        aftercare.updated_at = datetime.utcnow()

        db.session.commit()
        flash('Aftercare guide updated successfully!', 'success')
        return redirect(url_for('admin_aftercare'))

    services = Service.query.filter_by(is_active=True).order_by(Service.name).all()
    return render_template('edit_aftercare.html', aftercare=aftercare, services=services)


@app.route('/admin/aftercare/delete/<int:aftercare_id>', methods=['POST'])
@login_required
def delete_aftercare(aftercare_id):
    """Delete aftercare guide"""
    aftercare = Aftercare.query.get_or_404(aftercare_id)
    db.session.delete(aftercare)
    db.session.commit()
    flash('Aftercare guide deleted.', 'success')
    return redirect(url_for('admin_aftercare'))


# ==================== ACTIVITY LOG / NOTIFICATIONS ====================

@app.route('/admin/notifications')
@login_required
def get_notifications():
    """API endpoint to get recent activity for notification bell"""
    # Get last 20 activities
    activities = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(20).all()
    unread_count = ActivityLog.query.filter_by(is_read=False).count()

    return jsonify({
        'unread_count': unread_count,
        'activities': [{
            'id': a.id,
            'icon': a.get_icon(),
            'action_type': a.action_type,
            'description': a.description,
            'is_read': a.is_read,
            'created_at': a.created_at.strftime('%d %b %H:%M'),
            'time_ago': get_time_ago(a.created_at)
        } for a in activities]
    })


@app.route('/admin/notifications/mark-read', methods=['POST'])
@login_required
def mark_notifications_read():
    """Mark all notifications as read"""
    ActivityLog.query.filter_by(is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'success': True})


@app.route('/admin/activity-log')
@login_required
def activity_log_page():
    """Full activity log page"""
    page = request.args.get('page', 1, type=int)
    per_page = 50

    activities = ActivityLog.query.order_by(ActivityLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template('admin_activity_log.html', activities=activities)


def get_time_ago(dt):
    """Get human-readable time ago string"""
    now = datetime.utcnow()
    diff = now - dt

    if diff.days > 0:
        if diff.days == 1:
            return 'Yesterday'
        elif diff.days < 7:
            return f'{diff.days} days ago'
        else:
            return dt.strftime('%d %b')
    elif diff.seconds >= 3600:
        hours = diff.seconds // 3600
        return f'{hours}h ago'
    elif diff.seconds >= 60:
        mins = diff.seconds // 60
        return f'{mins}m ago'
    else:
        return 'Just now'


# ==================== STAFF MANAGEMENT ====================

@app.route('/admin/staff')
@owner_required
def admin_staff():
    """Staff management page - owner only"""
    staff_users = AdminUser.query.order_by(AdminUser.role.desc(), AdminUser.name).all()
    return render_template('admin_staff.html', staff_users=staff_users)


@app.route('/admin/staff/add', methods=['GET', 'POST'])
@owner_required
def add_staff():
    """Add a new staff member"""
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        name = request.form['name'].strip()
        role = request.form.get('role', 'staff')

        # Check if username already exists
        if AdminUser.query.filter_by(username=username).first():
            flash('A user with this username already exists.', 'error')
            return render_template('add_staff.html')

        # Create new admin user
        admin_user = AdminUser(
            username=username,
            name=name,
            role=role
        )
        admin_user.set_password(password)

        db.session.add(admin_user)
        db.session.commit()

        flash(f'Staff member "{name}" added successfully!', 'success')
        return redirect(url_for('admin_staff'))

    return render_template('add_staff.html')


@app.route('/admin/staff/edit/<int:user_id>', methods=['GET', 'POST'])
@owner_required
def edit_staff(user_id):
    """Edit a staff member"""
    staff_user = AdminUser.query.get_or_404(user_id)

    if request.method == 'POST':
        staff_user.name = request.form['name'].strip()

        # Only allow changing username if it's not taken by someone else
        new_username = request.form['username'].strip().lower()
        existing = AdminUser.query.filter_by(username=new_username).first()
        if existing and existing.id != user_id:
            flash('This username is already taken.', 'error')
            return render_template('edit_staff.html', staff_user=staff_user)

        staff_user.username = new_username

        # Update password only if provided
        new_password = request.form.get('password', '').strip()
        if new_password:
            staff_user.set_password(new_password)

        # Update role (but don't allow demoting the last owner)
        new_role = request.form.get('role', 'staff')
        if staff_user.role == 'owner' and new_role == 'staff':
            owner_count = AdminUser.query.filter_by(role='owner', is_active=True).count()
            if owner_count <= 1:
                flash('Cannot demote the last owner. Create another owner first.', 'error')
                return render_template('edit_staff.html', staff_user=staff_user)
        staff_user.role = new_role

        db.session.commit()
        flash('Staff member updated successfully!', 'success')
        return redirect(url_for('admin_staff'))

    return render_template('edit_staff.html', staff_user=staff_user)


@app.route('/admin/staff/toggle/<int:user_id>', methods=['POST'])
@owner_required
def toggle_staff(user_id):
    """Enable/disable a staff member"""
    staff_user = AdminUser.query.get_or_404(user_id)

    # Don't allow disabling the last active owner
    if staff_user.role == 'owner' and staff_user.is_active:
        owner_count = AdminUser.query.filter_by(role='owner', is_active=True).count()
        if owner_count <= 1:
            flash('Cannot disable the last owner.', 'error')
            return redirect(url_for('admin_staff'))

    staff_user.is_active = not staff_user.is_active
    db.session.commit()

    status = 'enabled' if staff_user.is_active else 'disabled'
    flash(f'{staff_user.name} has been {status}.', 'success')
    return redirect(url_for('admin_staff'))


# Initialize database tables on startup (works for both local and production)
with app.app_context():
    db.create_all()
    print("Database tables created/verified!")

    # Run simple migrations for new columns (db.create_all doesn't add columns to existing tables)
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)

    # Add first_booking_date to client table if missing
    if 'client' in inspector.get_table_names():
        client_columns = [c['name'] for c in inspector.get_columns('client')]
        if 'first_booking_date' not in client_columns:
            try:
                db.session.execute(text('ALTER TABLE client ADD COLUMN first_booking_date TIMESTAMP'))
                db.session.commit()
                print("Added first_booking_date column to client table")
            except Exception as e:
                print(f"Migration note: {e}")
                db.session.rollback()

    # Create initial owner account if none exists
    owner_count = AdminUser.query.filter_by(role='owner').count()
    if owner_count == 0:
        # Create owner from environment variables
        owner = AdminUser(
            username=ADMIN_USERNAME,
            name='Owner',
            role='owner'
        )
        owner.set_password(ADMIN_PASSWORD)
        db.session.add(owner)
        db.session.commit()
        print(f"Created initial owner account: {ADMIN_USERNAME}")

    # Seed default email templates if none exist
    from models import EmailTemplate
    if EmailTemplate.query.count() == 0:
        default_templates = [
            EmailTemplate(
                name='Promotion Announcement',
                description='Announce a special offer or discount',
                subject='Special Offer Just For You, {name}!',
                category='promotion',
                is_default=True,
                content='''<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
<h2 style="color: #c9a962;">Hi {name}!</h2>

<p>We've got something special just for you...</p>

<div style="background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center;">
<h3 style="color: #333; margin: 0;">YOUR EXCLUSIVE OFFER</h3>
<p style="font-size: 24px; color: #c9a962; font-weight: bold;">[Insert your offer here]</p>
<p style="color: #666;">Valid until [date]</p>
</div>

<p>Book your appointment today to take advantage of this offer!</p>

<p style="margin-top: 30px;">
<a href="https://whitethornpiercing.co.uk/book" style="background: #c9a962; color: #142b26; padding: 12px 30px; text-decoration: none; border-radius: 5px; font-weight: bold;">BOOK NOW</a>
</p>

<p style="color: #888; margin-top: 30px;">See you soon!<br>White Thorn Piercing</p>
</div>'''
            ),
            EmailTemplate(
                name='New Arrival Announcement',
                description='Announce new jewellery or services',
                subject='Something New Just Arrived! ✨',
                category='announcement',
                is_default=True,
                content='''<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
<h2 style="color: #c9a962;">Hi {name}!</h2>

<p>Exciting news - we have something new to share with you!</p>

<div style="background: #142b26; color: #f5f1e8; padding: 25px; border-radius: 8px; margin: 20px 0;">
<h3 style="color: #c9a962; margin-top: 0;">NEW ARRIVALS</h3>
<p>[Describe your new products or services here]</p>
</div>

<p>Pop in to see them in person, or book an appointment to get yours!</p>

<p style="margin-top: 30px;">
<a href="https://whitethornpiercing.co.uk/book" style="background: #c9a962; color: #142b26; padding: 12px 30px; text-decoration: none; border-radius: 5px; font-weight: bold;">BOOK APPOINTMENT</a>
</p>

<p style="color: #888; margin-top: 30px;">White Thorn Piercing</p>
</div>'''
            ),
            EmailTemplate(
                name='We Miss You',
                description='Re-engage clients who haven\'t visited recently',
                subject="It's Been a While, {name}! We Miss You 💜",
                category='reengagement',
                is_default=True,
                content='''<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
<h2 style="color: #c9a962;">Hi {name}!</h2>

<p>It's been a while since we last saw you, and we wanted to check in!</p>

<p>Whether you're thinking about a new piercing, need a check-up on an existing one, or just want to browse our latest jewellery collection - we'd love to see you.</p>

<div style="background: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #c9a962;">
<strong>Quick reminder:</strong> If you had a piercing done with us, it's always a good idea to come in for a check-up to make sure everything is healing perfectly!
</div>

<p style="margin-top: 30px;">
<a href="https://whitethornpiercing.co.uk/book" style="background: #c9a962; color: #142b26; padding: 12px 30px; text-decoration: none; border-radius: 5px; font-weight: bold;">BOOK YOUR VISIT</a>
</p>

<p style="color: #888; margin-top: 30px;">Hope to see you soon!<br>White Thorn Piercing</p>
</div>'''
            ),
        ]

        for template in default_templates:
            db.session.add(template)
        db.session.commit()
        print("Created default email templates")

# Start the reminder scheduler (runs in background thread)
start_reminder_scheduler()


if __name__ == '__main__':
    # Local development
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('DEBUG', 'true').lower() == 'true'

    print("\n" + "=" * 50)
    print("BOOKING SYSTEM STARTED")
    print("=" * 50)
    print(f"Customer booking: http://localhost:{port}/book")
    print(f"Admin login:      http://localhost:{port}/admin/login")
    print(f"Admin credentials: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
    print("=" * 50 + "\n")

    app.run(debug=debug, port=port, host='0.0.0.0')
