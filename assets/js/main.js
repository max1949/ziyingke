// Language switcher. English is the default for first-time visitors.
const languageButtons = document.querySelectorAll('[data-lang-switch]');
const translatableNodes = document.querySelectorAll('[data-en][data-zh]');

function updateYear() {
  const yearEl = document.getElementById('year');
  if (yearEl) yearEl.textContent = new Date().getFullYear();
}

function setLanguage(lang) {
  const nextLang = lang === 'zh' ? 'zh' : 'en';
  document.documentElement.lang = nextLang === 'zh' ? 'zh-CN' : 'en';
  translatableNodes.forEach(node => {
    node.innerHTML = node.dataset[nextLang];
  });
  languageButtons.forEach(button => {
    const isActive = button.dataset.langSwitch === nextLang;
    button.classList.toggle('active', isActive);
    button.setAttribute('aria-pressed', String(isActive));
  });
  localStorage.setItem('bkGtaLanguage', nextLang);
  updateYear();
}

if (languageButtons.length && translatableNodes.length) {
  languageButtons.forEach(button => {
    button.addEventListener('click', () => setLanguage(button.dataset.langSwitch));
  });
  setLanguage(localStorage.getItem('bkGtaLanguage') || 'en');
}

// 移动端导航切换
const navToggle = document.getElementById('navToggle');
const navLinks = document.getElementById('navLinks');
if (navToggle && navLinks) {
  navToggle.addEventListener('click', () => navLinks.classList.toggle('open'));
  navLinks.querySelectorAll('a').forEach(a =>
    a.addEventListener('click', () => navLinks.classList.remove('open'))
  );
}

// FAQ 手风琴
document.querySelectorAll('.faq-item').forEach(item => {
  const q = item.querySelector('.faq-q');
  const a = item.querySelector('.faq-a');
  q.addEventListener('click', () => {
    const isOpen = item.classList.contains('open');
    document.querySelectorAll('.faq-item').forEach(other => {
      other.classList.remove('open');
      other.querySelector('.faq-a').style.maxHeight = null;
    });
    if (!isOpen) {
      item.classList.add('open');
      a.style.maxHeight = a.scrollHeight + 'px';
    }
  });
});

// 页脚年份
updateYear();
