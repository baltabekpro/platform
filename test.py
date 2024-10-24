@dp.message(F.text == "📊 Посмотреть оценки учеников")
async def show_student_grades(message: types.Message):
    if not is_teacher(message.from_user.id):
        await message.reply("Эта функция доступна только для учителей.")
        return
    
    classes = get_teacher_classes(message.from_user.id)
    if not classes:
        await message.reply("У вас пока нет классов.")
        return
    
    response = "📊 Оценки учеников по классам:\n\n"
    
    for class_id, class_name in classes:
        grades = get_student_grades(class_id)
        if grades:
            response += f"Класс: {class_name}\n"
            for student_name, assignment_text, evaluation in grades:
                response += f"👤 Студент: {student_name}\n"
                response += f"📝 Задание: {assignment_text}\n"
                response += f"📈 Оценка: {evaluation}/10\n\n"
        else:
            response += f"Класс: {class_name}\nНет оценок для этого класса.\n\n"
    
    await message.reply(response or "Нет оценок для всех классов.", parse_mode=ParseMode.MARKDOWN)
