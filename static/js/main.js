// Voting functionality
$(document).ready(function() {
    const csrfToken = $('meta[name="csrf-token"]').attr('content');

    if (csrfToken) {
        $.ajaxSetup({
            headers: {
                'X-CSRF-Token': csrfToken
            }
        });

        $('form[method="POST"], form[method="post"]').each(function() {
            const form = $(this);
            if (form.find('input[name="_csrf_token"]').length === 0) {
                form.append(`<input type="hidden" name="_csrf_token" value="${csrfToken}">`);
            }
        });
    }

    $('.vote-btn').click(function() {
        const button = $(this);
        const postId = button.data('post-id');
        const voteType = Number(button.data('vote-type'));

        $.ajax({
            url: `/post/${postId}/vote`,
            method: 'POST',
            data: {
                vote_type: voteType
            },
            success: function(response) {
                if (response.success) {
                    // Update vote count display
                    const voteContainer = button.closest('.vote-buttons');
                    const voteCountSpan = voteContainer.find('.vote-count-display');
                    voteCountSpan.text(response.vote_count);

                    // Update button styles
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
            error: function(xhr) {
                if (xhr.status === 401) {
                    window.location.href = '/auth/login';
                } else {
                    alert('An error occurred. Please try again.');
                }
            }
        });
    });

    // Auto-dismiss alerts after 5 seconds
    setTimeout(function() {
        $('.alert').fadeOut('slow', function() {
            $(this).remove();
        });
    }, 5000);

    // Tag search autocomplete
    $('#tags').on('input', function() {
        const query = $(this).val();
        const lastComma = query.lastIndexOf(',');
        const lastTag = lastComma === -1 ? query : query.substring(lastComma + 1).trim();

        if (lastTag.length > 1) {
            $.ajax({
                url: '/api/tags/search',
                data: { q: lastTag },
                success: function(tags) {
                    // Simple autocomplete suggestion
                    if (tags.length > 0 && lastTag !== tags[0].name) {
                        const suggestion = lastComma === -1 ?
                            tags[0].name :
                            query.substring(0, lastComma + 1) + ' ' + tags[0].name;

                        // Show suggestion (you can implement a dropdown)
                        console.log('Suggested tag:', tags[0].name);
                    }
                }
            });
        }
    });

    // Confirm delete actions
    $('form[action*="delete"]').submit(function(e) {
        if (!confirm('Are you sure you want to delete this item? This action cannot be undone.')) {
            e.preventDefault();
        }
    });
});

// Add timestamp to posts
function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = Math.floor((now - date) / 1000);

    if (diff < 60) return `${diff} seconds ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)} minutes ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} hours ago`;
    if (diff < 604800) return `${Math.floor(diff / 86400)} days ago`;
    return date.toLocaleDateString();
}
