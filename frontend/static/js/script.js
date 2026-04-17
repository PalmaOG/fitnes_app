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

// index.html
function closeFirstLogin() 
{
  document.getElementById('profileModal').remove();
}

function reloadHtml() {
    document.body.classList.add('reloading');
     setTimeout(function() {
        location.reload();
    }, 500);  
}



// ========== НОВЫЙ КОД ДЛЯ ЛОАДЕРА ==========
// Перехватываем отправку формы профиля
const profileForm = document.getElementById('profileForm');
const loadingOverlay = document.getElementById('loadingOverlay');
const submitBtn = document.getElementById('submitProfileBtn');

if (profileForm) {
    profileForm.addEventListener('submit', async function(e) {
        e.preventDefault(); // Останавливаем стандартную отправку
        
        // Показываем лоадер
        if (loadingOverlay) {
            loadingOverlay.classList.remove('hidden');
        }
        
        // Блокируем кнопку отправки
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = 'Сохранение...';
        }
        
        // Собираем данные формы
        const formData = new FormData(profileForm);
        
        try {
            // Отправляем запрос на сервер
            const response = await fetch('/api/intro', {
                method: 'POST',
                body: formData
            });
            
            // Проверяем статус ответа
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            // Получаем JSON ответ от сервера
            const result = await response.json();
            console.log('Сервер вернул:', result);
            
            // Здесь можно обработать полученные тренировки
            if (result.success) {
                // Сохраняем тренировки в localStorage или глобальную переменную
                if (result.recommendations) {
                    localStorage.setItem('recommendedWorkouts', JSON.stringify(result.recommendations));
                }
                
                // Показываем уведомление об успехе
                showNotification('success', result.message || 'Профиль сохранен! Идет перенаправление...');
                
                // Перенаправляем на страницу с подобранными тренировками
                setTimeout(() => {
                    window.location.href = '/recommended-workouts';
                }, 1500);
            } else {
                throw new Error(result.error || 'Ошибка при сохранении');
            }
            
        } catch (error) {
            console.error('Ошибка:', error);
            showNotification('error', 'Произошла ошибка при сохранении. Попробуйте еще раз.');
            
            // Скрываем лоадер
            if (loadingOverlay) {
                loadingOverlay.classList.add('hidden');
            }
            
            // Разблокируем кнопку
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = 'Сохранить';
            }
        }
    });
}

// Функция для показа уведомлений
function showNotification(type, message) {
    // Удаляем существующие уведомления
    const existingNotifications = document.querySelectorAll('.custom-notification');
    existingNotifications.forEach(notif => notif.remove());
    
    // Создаем уведомление
    const notification = document.createElement('div');
    notification.className = `custom-notification fixed bottom-4 right-4 z-50 px-4 py-3 rounded-xl shadow-lg max-w-md ${
        type === 'success' ? 'bg-emerald-100 text-emerald-700 border border-emerald-200' : 'bg-red-100 text-red-700 border border-red-200'
    }`;
    notification.innerHTML = `
        <div class="flex items-center gap-2">
            ${type === 'success' ? 
                '<svg class="h-5 w-5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>' :
                '<svg class="h-5 w-5" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>'
            }
            <span>${message}</span>
        </div>
    `;
    
    document.body.appendChild(notification);
    
    // Автоматическое скрытие через 4 секунды
    setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transition = 'opacity 0.3s';
        setTimeout(() => notification.remove(), 300);
    }, 4000);
}

// Функция для отображения подобранных тренировок (вызовите ее на странице /recommended-workouts)
function displayRecommendedWorkouts() {
    const workouts = localStorage.getItem('recommendedWorkouts');
    if (workouts) {
        const workoutsData = JSON.parse(workouts);
        console.log('Подобранные тренировки:', workoutsData);
        // Здесь код для отображения карточек тренировок
        return workoutsData;
    }
    return [];
}