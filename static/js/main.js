$(document).ready(function () {
    const csrfToken = $('meta[name="csrf-token"]').attr('content');
    const backToTopButton = $('#backToTop');
    const contentField = $('#content');
    const contentCounter = $('#contentCounter');

    if (csrfToken) {
        $.ajaxSetup({
            headers: {
                'X-CSRF-Token': csrfToken
            }
        });

        $('form[method="POST"], form[method="post"]').each(function () {
            const form = $(this);
            if (form.find('input[name="_csrf_token"]').length === 0) {
                form.append(`<input type="hidden" name="_csrf_token" value="${csrfToken}">`);
            }
        });
    }

    $('.vote-btn').click(function () {
        const button = $(this);
        const postId = button.data('post-id');
        const voteType = Number(button.data('vote-type'));

        $.ajax({
            url: `/post/${postId}/vote`,
            method: 'POST',
            data: {
                vote_type: voteType
            },
            success: function (response) {
                if (response.success) {
                    const voteContainer = button.closest('.vote-buttons');
                    const voteCountSpan = voteContainer.find('.vote-count-display');
                    voteCountSpan.text(response.vote_count);

                    const upvoteBtn = voteContainer.find('.vote-btn[data-vote-type="1"]');
                    const downvoteBtn = voteContainer.find('.vote-btn[data-vote-type="-1"]');
                    upvoteBtn.removeClass('btn-success').addClass('btn-outline-success');
                    downvoteBtn.removeClass('btn-danger').addClass('btn-outline-danger');

                    if (response.user_vote === 1) {
                        upvoteBtn.removeClass('btn-outline-success').addClass('btn-success');
                    }

                    if (response.user_vote === -1) {
                        downvoteBtn.removeClass('btn-outline-danger').addClass('btn-danger');
                    }
                }
            },
            error: function (xhr) {
                if (xhr.status === 401) {
                    window.location.href = '/auth/login';
                } else {
                    alert('An error occurred. Please try again.');
                }
            }
        });
    });

    setTimeout(function () {
        $('.auto-dismiss-alert').fadeOut('slow', function () {
            $(this).remove();
        });
    }, 4000);

    $('#tags').on('input', function () {
        const query = $(this).val();
        const lastComma = query.lastIndexOf(',');
        const lastTag = lastComma === -1 ? query : query.substring(lastComma + 1).trim();

        if (lastTag.length > 1) {
            $.ajax({
                url: '/api/tags/search',
                data: { q: lastTag }
            });
        }
    });

    $('form[action*="delete"]').submit(function (e) {
        const confirmed = $(this).data('confirmed');
        if (!confirmed && !confirm('Are you sure you want to delete this item? This action cannot be undone.')) {
            e.preventDefault();
        }
    });

    function updateContentCounter() {
        if (!contentField.length || !contentCounter.length) {
            return;
        }
        contentCounter.text(contentField.val().length);
    }

    updateContentCounter();
    contentField.on('input', updateContentCounter);

    $(window).on('scroll', function () {
        if ($(window).scrollTop() > 300) {
            backToTopButton.addClass('show');
        } else {
            backToTopButton.removeClass('show');
        }
    });

    backToTopButton.on('click', function () {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    const quizSteps = $('.quiz-step');
    if (quizSteps.length) {
        let currentStep = 0;
        const progressBar = $('#quizProgressBar');
        const prevStep = $('#prevStep');
        const nextStep = $('#nextStep');
        const submitQuiz = $('#submitQuiz');

        function renderQuizStep() {
            quizSteps.addClass('d-none').eq(currentStep).removeClass('d-none');
            const progress = ((currentStep + 1) / quizSteps.length) * 100;
            progressBar.css('width', `${progress}%`);
            prevStep.toggleClass('d-none', currentStep === 0);
            nextStep.toggleClass('d-none', currentStep === quizSteps.length - 1);
            submitQuiz.toggleClass('d-none', currentStep !== quizSteps.length - 1);
        }

        function currentAnswered() {
            return quizSteps.eq(currentStep).find('input[type="radio"]:checked').length > 0;
        }

        $('.quiz-option-card').on('click', function () {
            const input = $(this).find('input[type="radio"]');
            input.prop('checked', true).trigger('change');
            $(this).closest('.row').find('.quiz-option-card').removeClass('selected');
            $(this).addClass('selected');
        });

        $('input[type="radio"]').each(function () {
            if ($(this).is(':checked')) {
                $(this).closest('.quiz-option-card').addClass('selected');
            }
        });

        nextStep.on('click', function () {
            if (!currentAnswered()) {
                alert('Please select an answer before continuing.');
                return;
            }
            currentStep = Math.min(currentStep + 1, quizSteps.length - 1);
            renderQuizStep();
        });

        prevStep.on('click', function () {
            currentStep = Math.max(currentStep - 1, 0);
            renderQuizStep();
        });

        renderQuizStep();
    }

    $('#shareQuizResult').on('click', function () {
        const shareText = $(this).data('share-text');
        if (!shareText) {
            return;
        }
        navigator.clipboard.writeText(shareText).then(function () {
            alert('Result copied to clipboard.');
        });
    });
    
    document.querySelectorAll('.auth-eye-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const wrap = btn.closest('.auth-input-wrap');
            const input = wrap.querySelector('.auth-input');
            const icon = btn.querySelector('i');
            if (input.type === 'password') {
                input.type = 'text';
                icon.classList.replace('fa-eye', 'fa-eye-slash');
            } else {
                input.type = 'password';
                icon.classList.replace('fa-eye-slash', 'fa-eye');
            }
        });
    });
});
