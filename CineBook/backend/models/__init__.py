"""MongoDB document conventions.

Collections and their key fields (ObjectIds unless noted):

users              {_id, name, email(unique), phone, password_hash, role, is_active, favourites[movie_id],
                    recently_viewed[movie_id], created_at, updated_at}
movies             {_id, slug(unique), title, description, genres[], languages[], duration_minutes, certificate,
                    release_date, status, rating, poster_url, poster_colors[], cast[], director, is_published,
                    avg_user_rating, review_count, created_at, updated_at}
cinemas            {_id, code(unique), name, city, address, amenities[], is_active}
screens            {_id, cinema_id, name, screen_type, layout{rows[{row, seats, category}], aisles_after[],
                    blocked_seats[]}, default_prices{category: price}, capacity}
showtimes          {_id, movie_id, cinema_id, screen_id, start_time(UTC), end_time, language, format,
                    prices{category: price}, layout(snapshot), capacity, is_published}
seat_locks         {_id, showtime_id, seat_id, state(held|booked), user_id, hold_id, booking_id, expires_at}
                    unique(showtime_id, seat_id)  <- database-enforced double-booking protection
seat_holds         {_id, user_id, showtime_id, seats[], status, expires_at, created_at}
bookings           {_id, reference(unique), user_id, showtime_id, status, seats[{seat_id, category, price}],
                    subtotal, discount, total, offer{}, movie_snapshot{}, cinema_snapshot{}, screen_snapshot{},
                    show_start, show_end, payment{}, refund{}, status_history[], created_at ...}
offers             {_id, code(unique), title, discount_type(percent|fixed), discount_value, min_booking_value,
                    max_discount, start_date, end_date, usage_limit, per_user_limit, used_count, is_active}
coupon_usage       {_id, offer_id, user_id, count}  unique(offer_id, user_id) -> per-customer limit counter
coupon_redemptions {_id, offer_id, code, user_id, booking_id(unique), discount, status, created_at}
reviews            {_id, movie_id, user_id, user_name, rating, comment, created_at}  unique(movie_id, user_id)
notifications      {_id, user_id, title, message, kind, read, created_at}
audit_logs         {_id, actor_id, actor_email, action, entity, entity_id, details, created_at}
settings           {_id: "booking_policy", ...policy fields}
"""
