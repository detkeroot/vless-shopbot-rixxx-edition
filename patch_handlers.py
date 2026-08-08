import sys

with open('src/shop_bot/bot/handlers.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

insert_idx = -1
for i, line in enumerate(lines):
    if line.strip() == 'return user_router':
        insert_idx = i
        break

if insert_idx != -1:
    code = """
    @user_router.message(Command(commands=["give"]))
    async def admin_give_key(message: types.Message, bot: Bot):
        admin_id = get_setting("admin_telegram_id")
        if str(message.from_user.id) != admin_id:
            return
            
        args = message.text.split()
        if len(args) != 3:
            await message.answer("Использование: /give <ID_пользователя_Telegram> <дней>\\nНапример: /give 123456789 3650")
            return
            
        try:
            target_user_id = int(args[1])
            days = int(args[2])
        except ValueError:
            await message.answer("❌ ID и дни должны быть числами.")
            return

        hosts = get_all_hosts()
        if not hosts:
            await message.answer("❌ В админке нет доступных серверов. Сначала добавь хост.")
            return
        
        host_name = hosts[0]['host_name']
        key_number = get_next_key_number(target_user_id)
        email = f"user{target_user_id}-key{key_number}@{host_name.replace(' ', '').lower()}.bot"
        
        processing_msg = await message.answer(f"Создаю ключ на {days} дней...")
        
        result = await xui_api.create_or_update_key_on_host(host_name, email, days)
        if not result:
            await processing_msg.edit_text("❌ Ошибка при создании ключа в панели RIXXX.")
            return
            
        key_id = add_new_key(target_user_id, host_name, result['client_uuid'], result['email'], result['expiry_timestamp_ms'])
        
        connection_string = result['connection_string']
        expiry_date = datetime.fromtimestamp(result['expiry_timestamp_ms'] / 1000)
        
        final_text = get_purchase_success_text("готова", key_number, expiry_date, connection_string)
        
        try:
            await bot.send_message(
                chat_id=target_user_id,
                text="🎁 Администратор выдал вам подписку!\\n\\n" + final_text,
                reply_markup=keyboards.create_key_info_keyboard(key_id)
            )
            await processing_msg.edit_text(f"✅ Успешно! Ключ на {days} дней выдан пользователю {target_user_id}.")
        except Exception as e:
            await processing_msg.edit_text(f"✅ Ключ создан, но отправить в ЛС не удалось (юзер не запустил бота?): {e}")

"""
    lines.insert(insert_idx, code)
    with open('src/shop_bot/bot/handlers.py', 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print("Команда /give успешно добавлена!")
else:
    print("Ошибка: не найдена нужная строка.")
