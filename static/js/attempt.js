(function () {
    const root = document.getElementById("attemptApp");
    if (!root) {
        return;
    }

    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) {
            return parts.pop().split(";").shift();
        }
        return "";
    }

    const csrfToken = getCookie("csrftoken");
    const stateTemplate = root.dataset.stateUrlTemplate;
    const answerUrl = root.dataset.answerUrl;
    const submitUrl = root.dataset.submitUrl;
    const eventUrl = root.dataset.eventUrl;
    const maxQuestions = Number(root.dataset.maxQuestions || "0");
    const allowFullscreen = root.dataset.allowFullscreen === "1";

    const timerEl = document.getElementById("timer");
    const promptEl = document.getElementById("questionPrompt");
    const metaEl = document.getElementById("questionMeta");
    const optionContainer = document.getElementById("optionContainer");
    const navContainer = document.getElementById("questionNav");
    const progressEl = document.getElementById("quizProgressBar");
    const alertEl = document.getElementById("systemAlert");

    const prevBtn = document.getElementById("prevBtn");
    const nextBtn = document.getElementById("nextBtn");
    const saveBtn = document.getElementById("saveBtn");
    const submitBtn = document.getElementById("submitQuizBtn");
    const fullscreenBtn = document.getElementById("fullscreenBtn");

    const state = {
        currentIndex: 0,
        currentQuestion: null,
        allowBackNavigation: true,
        remainingSeconds: Number(root.dataset.remaining || "0"),
        questionLoadedAt: Date.now(),
        navMap: new Map(),
        isSubmitting: false,
        lastSavedFingerprint: null,
        antiCheatEventTimes: {},
    };

    function stateUrl(index) {
        return stateTemplate.replace("999999", String(index));
    }

    function formatTime(totalSeconds) {
        const min = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
        const sec = Math.floor(totalSeconds % 60).toString().padStart(2, "0");
        return `${min}:${sec}`;
    }

    function showAlert(message, kind) {
        if (!alertEl) {
            return;
        }
        if (!message) {
            alertEl.classList.add("hidden");
            alertEl.textContent = "";
            return;
        }
        alertEl.className = `message message-${kind || "warning"}`;
        alertEl.textContent = message;
    }

    function updateTimer() {
        if (timerEl) {
            timerEl.textContent = formatTime(state.remainingSeconds);
        }
        const ratio = maxQuestions > 0 ? Math.max(0, (state.currentIndex + 1) / maxQuestions) : 0;
        if (progressEl) {
            progressEl.style.width = `${Math.min(100, ratio * 100)}%`;
        }
    }

    function readCurrentAnswer() {
        if (!state.currentQuestion) {
            return { selectedOptionId: null, textAnswer: "" };
        }

        if (state.currentQuestion.question_type === "short") {
            const textarea = optionContainer.querySelector("textarea");
            return {
                selectedOptionId: null,
                textAnswer: textarea ? textarea.value : "",
            };
        }

        const selected = optionContainer.querySelector('input[name="selected_option"]:checked');
        return {
            selectedOptionId: selected ? Number(selected.value) : null,
            textAnswer: "",
        };
    }

    async function sendEvent(eventType) {
        if (state.isSubmitting) {
            return;
        }

        const now = Date.now();
        const lastEvent = state.antiCheatEventTimes[eventType] || 0;
        if (now - lastEvent < 3000) {
            return;
        }
        state.antiCheatEventTimes[eventType] = now;

        try {
            await fetch(eventUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                },
                body: JSON.stringify({ event_type: eventType }),
            });
        } catch (error) {
            console.warn("Unable to send anti-cheat event", error);
        }
    }

    function renderNavigation(currentIndex) {
        if (!navContainer) {
            return;
        }

        navContainer.innerHTML = "";
        for (let i = 0; i < maxQuestions; i += 1) {
            const node = document.createElement("button");
            node.type = "button";
            node.textContent = String(i + 1);
            node.className = "question-nav-btn";

            const navItem = state.navMap.get(i);
            if (navItem && navItem.answered) {
                node.classList.add("answered");
            }
            if (i === currentIndex) {
                node.classList.add("current");
            }

            const canJump = state.allowBackNavigation || i <= currentIndex;
            if (!canJump) {
                node.disabled = true;
            }

            node.addEventListener("click", function () {
                loadQuestion(i);
            });
            navContainer.appendChild(node);
        }
    }

    function renderQuestion(question) {
        state.currentQuestion = question;
        state.questionLoadedAt = Date.now();

        metaEl.textContent = `Difficulty: ${question.difficulty} · Topic: ${question.topic} · Marks: ${question.marks}`;
        promptEl.textContent = question.prompt;
        optionContainer.innerHTML = "";

        if (question.question_type === "short") {
            const textarea = document.createElement("textarea");
            textarea.placeholder = "Type your answer here...";
            textarea.rows = 5;
            textarea.value = question.text_answer || "";
            optionContainer.appendChild(textarea);

            state.lastSavedFingerprint = JSON.stringify({
                q: question.id,
                o: null,
                t: question.text_answer || "",
            });
            return;
        }

        state.lastSavedFingerprint = JSON.stringify({
            q: question.id,
            o: question.selected_option_id || null,
            t: "",
        });

        (question.options || []).forEach(function (option) {
            const wrapper = document.createElement("label");
            wrapper.className = "option-card";

            const input = document.createElement("input");
            input.type = "radio";
            input.name = "selected_option";
            input.value = option.id;
            if (Number(question.selected_option_id) === Number(option.id)) {
                input.checked = true;
            }

            const textNode = document.createElement("span");
            textNode.textContent = option.text;

            wrapper.appendChild(input);
            wrapper.appendChild(textNode);
            optionContainer.appendChild(wrapper);
        });
    }

    async function saveCurrentAnswer(isAuto) {
        if (!state.currentQuestion || state.isSubmitting) {
            return true;
        }

        const elapsed = Math.floor((Date.now() - state.questionLoadedAt) / 1000);
        const answer = readCurrentAnswer();

        const payload = {
            question_id: state.currentQuestion.id,
            selected_option_id: answer.selectedOptionId,
            text_answer: answer.textAnswer,
            time_spent_seconds: Math.max(1, elapsed),
        };

        const fingerprint = JSON.stringify({
            q: payload.question_id,
            o: payload.selected_option_id,
            t: payload.text_answer,
        });
        if (isAuto && fingerprint === state.lastSavedFingerprint) {
            return true;
        }

        try {
            const response = await fetch(answerUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                },
                body: JSON.stringify(payload),
            });
            const data = await response.json().catch(function () {
                return {};
            });
            if (!response.ok || !data.ok) {
                showAlert(data.error || "Could not save answer.", "error");
                return false;
            }

            if (typeof data.remaining_seconds === "number") {
                state.remainingSeconds = data.remaining_seconds;
                updateTimer();
            }

            state.lastSavedFingerprint = fingerprint;
            state.navMap = new Map((data.navigation || []).map((item) => [item.order, item]));
            renderNavigation(state.currentIndex);
            if (!isAuto) {
                showAlert("Answer saved.", "success");
                setTimeout(function () {
                    showAlert("");
                }, 1100);
            }
            return true;
        } catch (error) {
            showAlert("Network error while saving.", "error");
            return false;
        }
    }

    async function submitAttempt(isAuto) {
        if (state.isSubmitting) {
            return;
        }

        if (!isAuto) {
            const confirmed = window.confirm("Submit this quiz now?");
            if (!confirmed) {
                return;
            }
        }

        state.isSubmitting = true;
        submitBtn.disabled = true;
        nextBtn.disabled = true;

        await saveCurrentAnswer(true);

        try {
            const response = await fetch(submitUrl, {
                method: "POST",
                headers: {
                    "X-CSRFToken": csrfToken,
                },
            });
            const data = await response.json();
            if (response.ok && data.ok && data.redirect_url) {
                window.location.href = data.redirect_url;
                return;
            }
            showAlert(data.error || "Submit failed.", "error");
        } catch (error) {
            showAlert("Network error during submission.", "error");
        } finally {
            state.isSubmitting = false;
            submitBtn.disabled = false;
            nextBtn.disabled = false;
        }
    }

    async function loadQuestion(index) {
        try {
            const response = await fetch(stateUrl(index), {
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            const data = await response.json().catch(function () {
                return {};
            });

            if (!response.ok) {
                showAlert(data.error || "Could not load question.", "error");
                return;
            }

            if (data.redirect_url) {
                window.location.href = data.redirect_url;
                return;
            }

            if (data.completed) {
                await submitAttempt(true);
                return;
            }

            if (data.expired) {
                window.location.href = data.redirect_url;
                return;
            }

            state.currentIndex = Number(data.current_index || 0);
            state.allowBackNavigation = Boolean(data.allow_back_navigation);
            state.remainingSeconds = Number(data.remaining_seconds || state.remainingSeconds);
            state.navMap = new Map((data.navigation || []).map((item) => [item.order, item]));
            showAlert("");

            renderQuestion(data.question);
            renderNavigation(state.currentIndex);
            updateTimer();

            prevBtn.disabled = state.currentIndex <= 0;
            nextBtn.textContent = state.currentIndex >= maxQuestions - 1 ? "Finish" : "Next";
        } catch (error) {
            showAlert("Could not load question.", "error");
        }
    }

    prevBtn.addEventListener("click", function () {
        if (state.currentIndex <= 0) {
            return;
        }
        loadQuestion(state.currentIndex - 1);
    });

    nextBtn.addEventListener("click", async function () {
        const ok = await saveCurrentAnswer(true);
        if (!ok) {
            return;
        }
        if (state.currentIndex >= maxQuestions - 1) {
            submitAttempt(false);
            return;
        }
        loadQuestion(state.currentIndex + 1);
    });

    saveBtn.addEventListener("click", function () {
        saveCurrentAnswer(false);
    });

    submitBtn.addEventListener("click", function () {
        submitAttempt(false);
    });

    if (allowFullscreen) {
        fullscreenBtn.classList.remove("hidden");
        fullscreenBtn.addEventListener("click", function () {
            if (document.documentElement.requestFullscreen) {
                document.documentElement.requestFullscreen();
            }
        });

        document.addEventListener("fullscreenchange", function () {
            if (!document.fullscreenElement) {
                sendEvent("fullscreen_exit");
            }
        });
    } else {
        fullscreenBtn.classList.add("hidden");
    }

    document.addEventListener("visibilitychange", function () {
        if (document.hidden) {
            sendEvent("tab_switch");
        }
    });

    setInterval(function () {
        state.remainingSeconds = Math.max(0, state.remainingSeconds - 1);
        updateTimer();
        if (state.remainingSeconds === 0 && !state.isSubmitting) {
            submitAttempt(true);
        }
    }, 1000);

    setInterval(function () {
        saveCurrentAnswer(true);
    }, 20000);

    loadQuestion(0);
})();
