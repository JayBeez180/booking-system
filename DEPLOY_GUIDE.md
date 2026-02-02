# Deployment Guide - White Thorn Piercing Booking System

This guide walks you through deploying the booking system to Railway.

## Prerequisites

- A [GitHub](https://github.com) account
- A [Railway](https://railway.app) account (can sign up with GitHub)
- Git installed on your computer

---

## Step 1: Push Code to GitHub

### First Time Setup

1. **Create a new repository on GitHub:**
   - Go to https://github.com/new
   - Name it something like `booking-system`
   - Keep it **Private** (recommended for business apps)
   - Don't initialize with README (we already have code)
   - Click **Create repository**

2. **Initialize Git and push your code:**
   ```bash
   cd /Users/jamesbeizsley/Desktop/booking-system

   # Initialize git repository
   git init

   # Add all files (respects .gitignore)
   git add .

   # Create first commit
   git commit -m "Initial commit - booking system"

   # Add GitHub as remote (replace YOUR_USERNAME with your GitHub username)
   git remote add origin https://github.com/YOUR_USERNAME/booking-system.git

   # Push to GitHub
   git branch -M main
   git push -u origin main
   ```

### Future Updates

After making changes, push them with:
```bash
git add .
git commit -m "Description of changes"
git push
```

---

## Step 2: Deploy to Railway

1. **Go to Railway:**
   - Visit https://railway.app
   - Click **Login** and sign in with GitHub

2. **Create a new project:**
   - Click **New Project**
   - Select **Deploy from GitHub repo**
   - Find and select your `booking-system` repository
   - Railway will start deploying automatically

3. **Add PostgreSQL Database:**
   - In your Railway project, click **New**
   - Select **Database** → **Add PostgreSQL**
   - Railway automatically creates and links the database
   - The `DATABASE_URL` environment variable is set automatically

---

## Step 3: Set Environment Variables

1. **Click on your web service** (not the database)
2. **Go to the Variables tab**
3. **Add these variables:**

| Variable | Value | Notes |
|----------|-------|-------|
| `SECRET_KEY` | (generate a random string) | Use: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_USERNAME` | your_admin_username | Choose a secure username |
| `ADMIN_PASSWORD` | your_secure_password | Choose a strong password! |
| `DEBUG` | false | Always false in production |

**To generate a secure SECRET_KEY**, run this in your terminal:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Step 4: Generate a Domain

1. **In Railway, click on your web service**
2. **Go to Settings tab**
3. **Under Networking, click "Generate Domain"**
4. Railway will give you a URL like `booking-system-production.up.railway.app`

---

## Step 5: Verify Deployment

1. **Visit your Railway URL**
2. **Test the customer booking page:** `https://your-app.up.railway.app/book`
3. **Test admin login:** `https://your-app.up.railway.app/admin/login`
4. **Log in with your ADMIN_USERNAME and ADMIN_PASSWORD**

---

## Troubleshooting

### View Logs
- In Railway, click your service → **Deployments** tab
- Click on a deployment to see build and runtime logs

### Common Issues

**"Application Error" or blank page:**
- Check the deployment logs for errors
- Ensure all environment variables are set
- Make sure DATABASE_URL was auto-configured

**Can't log in to admin:**
- Verify ADMIN_USERNAME and ADMIN_PASSWORD are set correctly
- Check for typos in the environment variables

**Database errors:**
- The database tables are created automatically on first run
- If you see migration errors, you may need to run migrations manually

### Manual Database Migration

If you need to run database migrations after adding new features:

1. In Railway, go to your PostgreSQL service
2. Click **Connect** to get connection details
3. You can run migrations locally by setting DATABASE_URL temporarily

---

## Custom Domain (Optional)

To use your own domain (e.g., `book.whitethornpiercing.com`):

1. **In Railway Settings → Networking**
2. **Click "Custom Domain"**
3. **Enter your domain**
4. **Add the CNAME record** Railway provides to your DNS settings
5. Railway handles SSL automatically

---

## Updating the App

When you make changes locally:

```bash
# Make your changes, then:
git add .
git commit -m "Description of what changed"
git push
```

Railway automatically detects the push and redeploys!

---

## Email Configuration

After deployment, configure email settings in the admin panel:
1. Go to Admin → Settings
2. Enter your SMTP settings (Gmail, SendGrid, etc.)
3. Enable email notifications

For Gmail, you'll need an "App Password":
1. Enable 2FA on your Google account
2. Go to https://myaccount.google.com/apppasswords
3. Generate a new app password for "Mail"
4. Use that password in SMTP settings

---

## Backup Reminder

Railway PostgreSQL includes automatic backups, but consider:
- Exporting client data periodically
- Keeping local backups of your code
- Testing your deployment after major changes

---

## Support

If you encounter issues:
1. Check Railway's status page: https://status.railway.app
2. Review Railway docs: https://docs.railway.app
3. Check the deployment logs for specific errors
