from flask_wtf import FlaskForm
from wtforms import DateField, SelectField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Optional

class AscensoForm(FlaskForm):
    alumno_id = SelectField("Alumno", coerce=int, validators=[DataRequired()])
    fecha = DateField("Fecha", validators=[DataRequired()], format="%Y-%m-%d")

    grado_anterior_id = SelectField("Grado anterior", coerce=int, validators=[DataRequired()])
    grado_nuevo_id = SelectField("Grado nuevo", coerce=int, validators=[DataRequired()])

    origen = SelectField(
        "Origen",
        choices=[("EXAMEN", "EXAMEN"), ("MANUAL", "MANUAL")],
        validators=[DataRequired()],
    )

    examen_id = SelectField("Examen", coerce=int, validators=[Optional()])  # 0 = ninguno
    observacion = TextAreaField("Observación", validators=[Optional()])

    submit = SubmitField("Guardar")