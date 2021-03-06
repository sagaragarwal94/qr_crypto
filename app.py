
import os
import base64
from io import StringIO
from flask import Flask, render_template, request, redirect, url_for, flash, session, \
    abort
from werkzeug.security import generate_password_hash, check_password_hash
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.login import LoginManager, UserMixin, login_user, logout_user, \
    current_user
from flask.ext.bootstrap import Bootstrap
from flask.ext.wtf import Form
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import Required, Length, EqualTo
import onetimepass
import pyqrcode
from flask.ext.qrcode import QRcode
from werkzeug.utils import secure_filename
import qrtools
import zbar
# create application instance
app = Flask(__name__)
app.config.from_object('config')

# initialize extensions
bootstrap = Bootstrap(app)
db = SQLAlchemy(app)
lm = LoginManager(app)
QRcode(app)



class User(UserMixin, db.Model):
    """User model."""
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True)
    password_hash = db.Column(db.String(128))
    otp_secret = db.Column(db.String(16))
    wallet =  db.Column(db.Integer)
    phone_number = db.Column(db.String(11), unique = True)

    def __init__(self, **kwargs):
        super(User, self).__init__(**kwargs)
        if self.otp_secret is None:
            # generate a random secret
            self.otp_secret = base64.b32encode(os.urandom(10)).decode('utf-8')

    @property
    def password(self):
        raise AttributeError('password is not a readable attribute')

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_totp_uri(self):
        return 'otpauth://totp/2FA-Demo:{0}?secret={1}&issuer=2FA-Demo' \
            .format(self.username, self.otp_secret)

    def verify_totp(self, token):
        return onetimepass.valid_totp(token, self.otp_secret)


@lm.user_loader
def load_user(user_id):
    """User loader callback for Flask-Login."""
    return User.query.get(int(user_id))


class RegisterForm(Form):
    """Registration form."""
    username = StringField('Username', validators=[Required(), Length(1, 64)])
    password = PasswordField('Password', validators=[Required()])
    password_again = PasswordField('Password again',
                                   validators=[Required(), EqualTo('password')])
    phone_number =StringField('Phone Number', validators=[Required(), Length(1, 13)])
    submit = SubmitField('Register')


class LoginForm(Form):
    """Login form."""
    username = StringField('Username', validators=[Required(), Length(1, 64)])
    password = PasswordField('Password', validators=[Required()])
    token = StringField('Token', validators=[Required(), Length(6, 6)])
    submit = SubmitField('Login')

class creditsTransfer(Form):
    credits_transfer = StringField('Transfer Credits', validators=[Required(), Length(1, 10)])
    phone_number = StringField('Phone Number', validators=[Required(), Length(10)])
    submit = SubmitField('Transfer')

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration route."""
    if current_user.is_authenticated():
        # if user is logged in we get out of here
        return redirect(url_for('index'))
    form = RegisterForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is not None:
            flash('Username already exists.')
            return redirect(url_for('register'))
        # add new user to the database
        user = User(username=form.username.data, password=form.password.data, wallet = 100)
        db.session.add(user)
        db.session.commit()

        # redirect to the two-factor auth page, passing username in session
        session['username'] = user.username
        return redirect(url_for('two_factor_setup'))
    return render_template('register.html', form=form)



@app.route('/twofactor')
def two_factor_setup():
    if 'username' not in session:
        return redirect(url_for('index'))
    user = User.query.filter_by(username=session['username']).first()
    if user is None:
        return redirect(url_for('index'))
    # since this page contains the sensitive qrcode, make sure the browser
    # does not cache it
    return render_template('two-factor-setup.html'), 200, {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'}


@app.route('/give_money', methods=['GET', 'POST'])
def give_money():
    form = creditsTransfer()
    if form.validate_on_submit() :
        img = form.phone_number.data + form.credits_transfer.data
        count = int(form.credits_transfer.data)
        user = User.query.filter_by(id=current_user.id).first()
        user.wallet = user.wallet - count 
        db.session.add(user)
        db.session.commit()
        print current_user.wallet
        print user.wallet
        return redirect(url_for('qr_gen',img=img)) 
    return render_template('give_money.html', form=form)

@app.route('/take_money', methods = ['GET', 'POST'])
def take_money():
    pass

@app.route('/qr_gen/<img>')
def qr_gen(img):
    user = User.query.filter_by(id=current_user.id).first()
    print user.wallet
    return render_template('qr_gen.html',img=img)

@app.route('/qrcode')
def qrcode():
    if 'username' not in session:
        abort(404)
    user = User.query.filter_by(username=session['username']).first()
    if user is None:
        abort(404)

    # for added security, remove username from session
    del session['username']

    # render qrcode for FreeTOTP
    url = pyqrcode.create(user.get_totp_uri())
    stream = StringIO()
    url.svg(stream, scale=3)
    return stream.getvalue().encode('utf-8'), 200, {
        'Content-Type': 'image/svg+xml',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'}


@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login route."""
    if current_user.is_authenticated():
        # if user is logged in we get out of here
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.verify_password(form.password.data) or \
                not user.verify_totp(form.token.data):
            flash('Invalid username, password or token.')
            return redirect(url_for('login'))

        # log user in
        login_user(user)
        flash('You are now logged in!')
        return redirect(url_for('index'))
    return render_template('login.html', form=form)


@app.route('/logout')
def logout():
    """User logout route."""
    print "logout"
    logout_user()
    return redirect(url_for('index'))

@app.route('/qr_decode', methods=['GET','POST'])
def qr_decode():
    if request.method == 'POST':
        f = request.files['file']
        qr = qrtools.QR()
        qr.decode(f)
        l = qr.data
        phone=l[0:10]
        cre = l[10:]
        user = User.query.filter_by(id=current_user.id).first()
        user.wallet = user.wallet + int(cre) 
        db.session.add(user)
        db.session.commit()
        print current_user.wallet
        print user.wallet

    return render_template('qr_decode.html')  
        

# create database tables if they don't exist yet
db.create_all()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port = 5026, debug=True)
