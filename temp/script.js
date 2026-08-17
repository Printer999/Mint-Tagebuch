const weekDays = [
  "Montag",
  "Dienstag",
  "Mittwoch",
  "Donnerstag",
  "Freitag",
];

const STORAGE_KEY = "weekly-diary-v1";

let selectedDay = weekDays[0];
let currentRating = 0;

const dayTabs = document.getElementById("day-tabs");
const selectedDayLabel = document.getElementById("selected-day-label");
const daySummary = document.getElementById("day-summary");
const starRating = document.getElementById("star-rating");
const entriesList = document.getElementById("entries-list");
const entryForm = document.getElementById("entry-form");
const entryText = document.getElementById("entry-text");

function getDefaultData() {
  return weekDays.reduce((acc, day) => {
    acc[day] = [];
    return acc;
  }, {});
}

function loadEntries() {
  const saved = localStorage.getItem(STORAGE_KEY);

  if (!saved) {
    const defaultData = getDefaultData();
    localStorage.setItem(STORAGE_KEY, JSON.stringify(defaultData));
    return defaultData;
  }

  try {
    const parsed = JSON.parse(saved);
    return {
      ...getDefaultData(),
      ...parsed,
    };
  } catch (error) {
    console.error("Fehler beim Laden der Tagebucheinträge:", error);
    const fallback = getDefaultData();
    localStorage.setItem(STORAGE_KEY, JSON.stringify(fallback));
    return fallback;
  }
}

function saveEntries(data) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

function renderDayTabs() {
  dayTabs.innerHTML = "";

  weekDays.forEach((day) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `day-tab ${day === selectedDay ? "active" : ""}`;
    button.textContent = day;
    button.setAttribute("aria-pressed", String(day === selectedDay));

    button.addEventListener("click", () => {
      selectedDay = day;
      currentRating = 0;
      entryText.value = "";
      render();
    });

    dayTabs.appendChild(button);
  });
}

function getDayEntries() {
  const data = loadEntries();
  return data[selectedDay] || [];
}

function renderStars() {
  starRating.innerHTML = "";

  for (let value = 1; value <= 5; value += 1) {
    const star = document.createElement("button");
    star.type = "button";
    star.className = `star-btn ${value <= currentRating ? "active" : ""}`;
    star.textContent = "★";
    star.setAttribute("aria-label", `${value} Sterne`);
    star.setAttribute("aria-pressed", String(value === currentRating));

    star.addEventListener("click", () => {
      currentRating = value;
      renderStars();
    });

    starRating.appendChild(star);
  }
}

function renderEntries() {
  const entries = getDayEntries();
  const count = entries.length;
  daySummary.textContent = `${count} ${count === 1 ? "Eintrag" : "Einträge"}`;
  selectedDayLabel.textContent = selectedDay;

  if (count === 0) {
    entriesList.innerHTML = '<li class="empty-state">Noch keine Einträge für diesen Tag. Schreibe deine Gedanken auf.</li>';
    return;
  }

  entriesList.innerHTML = "";

  entries
    .slice()
    .reverse()
    .forEach((entry) => {
      const listItem = document.createElement("li");
      listItem.className = "entry-item";

      const header = document.createElement("div");
      header.className = "entry-header";

      const date = document.createElement("span");
      date.className = "entry-date";
      date.textContent = entry.date;

      const rating = document.createElement("span");
      rating.className = "entry-rating";
      rating.textContent = "★".repeat(entry.rating) + "☆".repeat(5 - entry.rating);

      header.append(date, rating);

      const text = document.createElement("p");
      text.className = "entry-text";
      text.textContent = entry.text;

      listItem.append(header, text);
      entriesList.appendChild(listItem);
    });
}

function render() {
  renderDayTabs();
  renderStars();
  renderEntries();
}

entryForm.addEventListener("submit", (event) => {
  event.preventDefault();

  const text = entryText.value.trim();

  if (!text) {
    entryText.focus();
    return;
  }

  if (currentRating === 0) {
    currentRating = 3;
  }

  const data = loadEntries();
  data[selectedDay].push({
    id: Date.now(),
    text,
    rating: currentRating,
    date: new Date().toLocaleString("de-DE", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }),
  });

  saveEntries(data);
  entryText.value = "";
  currentRating = 0;
  render();
});

render();
