// Получаем элементы форм и кнопки переключения
const loginCard = document.getElementById('login-card');
const registerCard = document.getElementById('register-card');
const showRegisterBtn = document.getElementById('show-register-btn');
const showLoginBtn = document.getElementById('show-login-btn');

const pass = document.getElementById('pass');
const passcheck = document.getElementById('passcheck');

// Функция переключения
function toggleForms(showLogin) {
  if (showLogin) {
    // Показываем вход, скрываем регистрацию
    loginCard.classList.remove('hidden');
    registerCard.classList.add('hidden');
  } else {
    // Показываем регистрацию, скрываем вход
    registerCard.classList.remove('hidden');
    loginCard.classList.add('hidden');
  }
}

showRegisterBtn.addEventListener('click', function(e) {
  e.preventDefault();
  toggleForms(false); // показать регистрацию
});

showLoginBtn.addEventListener('click', function(e) {
  e.preventDefault();
  toggleForms(true); 
});

passcheck.addEventListener('input', function() {
  const currentValue = this.value; // или input.value
  console.log('Текущее значение:', currentValue);
    if (pass.value == currentValue)
    {
      console.log('Пароли одиннаковые')
      passcheck.classList.remove('focus:ring-red-300/70');
      passcheck.classList.remove('focus:border-red-600');
      passcheck.classList.add('focus:ring-emerald-300/70');
      passcheck.classList.add('focus:border-emerald-300');  
    }
    else
    {
      passcheck.classList.add('focus:ring-red-300/70');
      passcheck.classList.add('focus:border-red-600');
      passcheck.classList.remove('focus:ring-emerald-300/70');
      passcheck.classList.remove('focus:border-emerald-300'); 
      console.log('Пароли не одиннаковые')
    }
});

function closeNotification()
{
  const notification = document.getElementById('notification')
  notification.remove();
}

